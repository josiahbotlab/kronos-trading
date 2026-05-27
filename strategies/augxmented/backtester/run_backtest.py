#!/usr/bin/env python3
"""
Augxmented Strategy Backtester
================================
Fetches QQQ + SPY data, runs the Augxmented ICT strategy bar-by-bar,
and produces a performance report.

Data sources (in order):
  1. Local SQLite cache
  2. Alpaca API (if valid keys in .env)
  3. yfinance (free fallback — 5m data limited to ~60 days)

For 6+ months, 1h bars are available via yfinance. The backtester runs both
a 5m primary test and a 1h extended test when 5m data doesn't cover the
full requested range.

Usage:
    cd ~/trading-bot/kronos-trading
    python -m strategies.augxmented.backtester.run_backtest
    python -m strategies.augxmented.backtester.run_backtest --start 2025-09-25 --end 2026-03-25
    python -m strategies.augxmented.backtester.run_backtest --refresh
"""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT.parent / ".env")  # ~/trading-bot/.env

from strategies.templates.base_strategy import CandleData, Signal
from strategies.augxmented.strategy import AugxmentedStrategy
from strategies.augxmented.backtester.fetch_data import fetch_bars
from core.metrics import Trade, PerformanceReport, calculate_metrics

REPORTS_DIR = Path(__file__).parent / "reports"
FEE_RATE = 0.0001  # 1 bp slippage for QQQ (commission-free on Alpaca)


# ---------------------------------------------------------------------------
# Backtest engine
# ---------------------------------------------------------------------------

def run_backtest(
    qqq_candles: list[CandleData],
    spy_candles: list[CandleData],
    initial_capital: float = 10_000.0,
    label: str = "5m",
) -> tuple[PerformanceReport, float, list[Trade]]:
    """
    Run the Augxmented strategy on pre-loaded candle data.

    Returns (report, trades_per_day, trades).
    """
    if not qqq_candles:
        report = PerformanceReport(initial_capital=initial_capital)
        return report, 0.0, []

    # Build SPY lookup for time-aligned SMT
    spy_by_ts = {c.timestamp_ms: c for c in spy_candles}
    spy_timestamps = sorted(spy_by_ts.keys())

    # Initialize strategy
    strategy = AugxmentedStrategy()
    # For 1h bars, reduce min_history proportionally (1h = 12x fewer bars)
    if label == "1h":
        strategy.set_param("min_history", 50)
        strategy.set_param("max_hold_bars", 8)   # 8h max hold on 1h bars
        strategy.set_param("cooldown_bars", 1)
    strategy.on_init()

    # Backtest loop
    position = None  # (side, entry_price, entry_time, quantity, tag)
    equity = initial_capital
    trades: list[Trade] = []
    spy_history: list[CandleData] = []
    spy_ts_idx = 0
    signal_count = 0

    for i, candle in enumerate(qqq_candles):
        # Update SPY history up to current timestamp
        while spy_ts_idx < len(spy_timestamps) and spy_timestamps[spy_ts_idx] <= candle.timestamp_ms:
            spy_history.append(spy_by_ts[spy_timestamps[spy_ts_idx]])
            spy_ts_idx += 1
        if len(spy_history) > 200:
            spy_history = spy_history[-200:]
        strategy._spy_candles = spy_history

        # Feed candle to strategy
        strategy._update_history(candle)
        signal = strategy.on_candle(candle)

        if signal is None or signal.direction is None:
            continue

        # Position management
        if signal.direction == 0:
            if position is not None:
                # Use remaining_qty from strategy's tiered TP tracking
                remaining = signal.metadata.get('remaining_qty', 1.0)
                tp1_hit = signal.metadata.get('tp1_hit', False)
                tp2_hit = signal.metadata.get('tp2_hit', False)
                trade = _close_position(
                    position, candle,
                    exit_tag=signal.tag,
                    remaining_qty=remaining,
                    tp1_hit=tp1_hit,
                    tp2_hit=tp2_hit,
                )
                equity += trade.pnl
                trades.append(trade)
                strategy.on_trade(trade.pnl, trade.pnl_pct)
                position = None

        elif signal.direction in (1, -1):
            signal_count += 1
            # Flip opposite position
            if position is not None:
                pos_side = position[0]
                if (signal.direction == 1 and pos_side == "short") or \
                   (signal.direction == -1 and pos_side == "long"):
                    trade = _close_position(position, candle, exit_tag="augx_exit_flip")
                    equity += trade.pnl
                    trades.append(trade)
                    strategy.on_trade(trade.pnl, trade.pnl_pct)
                    position = None

            # Open new position
            if position is None:
                side = "long" if signal.direction == 1 else "short"
                notional = equity * signal.strength
                quantity = notional / candle.close
                fee = notional * FEE_RATE
                equity -= fee
                entry_atr = signal.metadata.get('atr', 0.0)
                position = (side, candle.close, candle.timestamp_ms, quantity, signal.tag, entry_atr)

        # Progress every 2000 bars
        if (i + 1) % 2000 == 0:
            print(f"    [{label}] {i+1:,}/{len(qqq_candles):,} bars | "
                  f"{len(trades)} trades | equity ${equity:,.2f}")

    # Close any open position at end
    if position is not None:
        trade = _close_position(position, qqq_candles[-1], exit_tag="augx_exit_end")
        equity += trade.pnl
        trades.append(trade)

    print(f"    [{label}] Done: {len(qqq_candles):,} bars, "
          f"{signal_count} entry signals, {len(trades)} trades, "
          f"equity ${equity:,.2f}")

    # Calculate metrics
    report = calculate_metrics(trades, initial_capital=initial_capital)
    trades_per_day = (report.total_trades / report.duration_days) if report.duration_days > 0 else 0.0

    return report, trades_per_day, trades


def _close_position(
    position: tuple,
    candle: CandleData,
    exit_tag: str = "",
    remaining_qty: float = 1.0,
    tp1_hit: bool = False,
    tp2_hit: bool = False,
) -> Trade:
    """
    Close a position with tiered TP blending.

    With tiered TPs, partial exits happened at intermediate levels:
      - TP1 hit: 50% exited at entry + 1.0*ATR
      - TP2 hit: 30% exited at entry + 1.8*ATR
      - Final exit: remaining fraction at current price
    """
    if len(position) == 6:
        side, entry_price, entry_time, quantity, tag, entry_atr = position
    else:
        side, entry_price, entry_time, quantity, tag = position
        entry_atr = 0.0
    tag = exit_tag or tag
    exit_price = candle.close
    sign = 1 if side == "long" else -1

    if entry_atr > 0 and (tp1_hit or tp2_hit):
        # Blended PnL across all realized TP tiers
        total_pnl = 0.0

        if tp1_hit:
            tp1_exit = entry_price + sign * entry_atr * 1.0
            total_pnl += sign * (tp1_exit - entry_price) * quantity * 0.50

            if tp2_hit:
                tp2_exit = entry_price + sign * entry_atr * 1.8
                total_pnl += sign * (tp2_exit - entry_price) * quantity * 0.30
                rem_frac = 0.20
            else:
                rem_frac = 0.50
        else:
            rem_frac = 1.0

        # Remaining portion exits at current price
        total_pnl += sign * (exit_price - entry_price) * quantity * rem_frac

        fee = (entry_price + exit_price) * quantity * FEE_RATE / 2
        total_pnl -= fee
        pnl = total_pnl
        pnl_pct = (pnl / (entry_price * quantity)) * 100
    else:
        pnl = sign * (exit_price - entry_price) * quantity
        pnl_pct = (pnl / (entry_price * quantity)) * 100
        fee = exit_price * quantity * FEE_RATE
        pnl -= fee

    return Trade(
        entry_time=entry_time,
        exit_time=candle.timestamp_ms,
        symbol="QQQ",
        side=side,
        entry_price=entry_price,
        exit_price=exit_price,
        quantity=quantity,
        pnl=pnl,
        pnl_pct=pnl_pct,
        fees=fee * 2,
        tag=tag,
    )


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def write_report(
    results: dict,
    start_date: str,
    end_date: str,
    initial_capital: float,
) -> Path:
    """Write combined markdown report and print console summary."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = REPORTS_DIR / f"backtest_{ts}.md"

    md_lines = [
        "# Augxmented Strategy Backtest Report",
        "",
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]

    for label, (report, trades_per_day, trades) in results.items():
        # Console output
        print(f"\n{'='*60}")
        print(f"  {label.upper()} RESULTS")
        print(f"{'='*60}")
        print(report.summary())
        print(f"  Trades/Day:       {trades_per_day:.2f}")

        if trades:
            long_trades = [t for t in trades if t.side == "long"]
            short_trades = [t for t in trades if t.side == "short"]
            print(f"  Long Trades:      {len(long_trades)}")
            print(f"  Short Trades:     {len(short_trades)}")

            exit_reasons = {}
            for t in trades:
                reason = t.tag.replace("augx_exit_", "").replace("augx_entry_", "entry:")
                exit_reasons[reason] = exit_reasons.get(reason, 0) + 1
            print(f"\n  Exit Breakdown:")
            for reason, count in sorted(exit_reasons.items(), key=lambda x: -x[1]):
                print(f"    {reason:20s} {count:4d}")

        # Markdown section
        data_note = ""
        if label == "5m":
            data_note = " (yfinance max 60 days)"
        elif label == "1h (6-month)":
            data_note = " (yfinance full range)"

        md_lines.extend([
            f"## {label.upper()} Backtest{data_note}",
            "",
            "### Parameters",
            "",
            "| Parameter | Value |",
            "|-----------|-------|",
            f"| Symbol | QQQ ({label.split()[0]}) |",
            f"| Period | {start_date} → {end_date} |",
            f"| Actual Data | {report.duration_days:.0f} days |",
            f"| Initial Capital | ${initial_capital:,.0f} |",
            f"| Fee Rate | {FEE_RATE*100:.3f}% per side |",
            "",
            "### Performance",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Total Return | {report.total_return_pct:+.2f}% (${report.total_return_usd:+,.2f}) |",
            f"| CAGR | {report.cagr_pct:.2f}% |",
            f"| Max Drawdown | {report.max_drawdown_pct:.2f}% (${report.max_drawdown_usd:,.2f}) |",
            f"| DD Duration | {report.max_drawdown_duration_hours:.1f} hours |",
            f"| Sharpe Ratio | {report.sharpe_ratio:.2f} |",
            f"| Sortino Ratio | {report.sortino_ratio:.2f} |",
            f"| Profit Factor | {report.profit_factor:.2f} |",
            f"| Return/DD | {report.return_dd_ratio:.2f}x |",
            "",
            "### Trade Statistics",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Total Trades | {report.total_trades} |",
            f"| Trades/Day | {trades_per_day:.2f} |",
            f"| Win Rate | {report.win_rate_pct:.1f}% |",
            f"| Avg Win | {report.avg_win_pct:+.2f}% |",
            f"| Avg Loss | {report.avg_loss_pct:+.2f}% |",
            f"| Best Trade | {report.best_trade_pct:+.2f}% |",
            f"| Worst Trade | {report.worst_trade_pct:+.2f}% |",
            f"| Avg Hold Time | {report.avg_holding_hours:.1f} hours |",
        ])

        if trades:
            long_trades = [t for t in trades if t.side == "long"]
            short_trades = [t for t in trades if t.side == "short"]
            long_wins = [t for t in long_trades if t.pnl > 0]
            short_wins = [t for t in short_trades if t.pnl > 0]

            md_lines.extend([
                f"| Long Trades | {len(long_trades)} "
                f"(WR {len(long_wins)/max(len(long_trades),1)*100:.0f}%) |",
                f"| Short Trades | {len(short_trades)} "
                f"(WR {len(short_wins)/max(len(short_trades),1)*100:.0f}%) |",
            ])

            # Exit reasons
            exit_reasons = {}
            for t in trades:
                reason = t.tag.replace("augx_exit_", "").replace("augx_entry_", "entry:")
                exit_reasons[reason] = exit_reasons.get(reason, 0) + 1

            md_lines.extend(["", "### Exit Reasons", "",
                             "| Reason | Count | % |",
                             "|--------|-------|---|"])
            for reason, count in sorted(exit_reasons.items(), key=lambda x: -x[1]):
                pct = count / max(len(trades), 1) * 100
                md_lines.append(f"| {reason} | {count} | {pct:.1f}% |")

            # Trade log sample
            md_lines.extend(["", "### Trade Log (sample)", "",
                             "| # | Side | Entry | Exit | PnL% | Tag |",
                             "|---|------|-------|------|------|-----|"])
            show_trades = trades[:50]
            if len(trades) > 60:
                show_trades.append(None)
                show_trades.extend(trades[-10:])

            for idx, t in enumerate(show_trades):
                if t is None:
                    md_lines.append("| ... | ... | ... | ... | ... | ... |")
                    continue
                entry_dt = datetime.fromtimestamp(
                    t.entry_time / 1000, tz=timezone.utc
                ).strftime("%m/%d %H:%M")
                exit_dt = datetime.fromtimestamp(
                    t.exit_time / 1000, tz=timezone.utc
                ).strftime("%m/%d %H:%M")
                md_lines.append(
                    f"| {idx+1} | {t.side} | {entry_dt} ${t.entry_price:.2f} | "
                    f"{exit_dt} ${t.exit_price:.2f} | {t.pnl_pct:+.2f}% | {t.tag} |"
                )

        md_lines.extend(["", "---", ""])

    md_lines.append("")
    report_path.write_text("\n".join(md_lines))
    print(f"\n  Report saved: {report_path}")
    return report_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Augxmented Strategy Backtester")
    parser.add_argument("--start", default="2025-09-25",
                        help="Start date YYYY-MM-DD (default: 2025-09-25)")
    parser.add_argument("--end", default="2026-03-25",
                        help="End date YYYY-MM-DD (default: 2026-03-25)")
    parser.add_argument("--capital", type=float, default=10_000.0,
                        help="Initial capital (default: $10,000)")
    parser.add_argument("--refresh", action="store_true",
                        help="Force re-fetch (ignore cache)")
    args = parser.parse_args()

    print("=" * 60)
    print("  AUGXMENTED BACKTESTER")
    print("=" * 60)
    print(f"  Period:  {args.start}  →  {args.end}")
    print(f"  Capital: ${args.capital:,.0f}")
    print(f"  Fee:     {FEE_RATE * 100:.3f}% per side (slippage)")
    print("-" * 60)

    results = {}

    # --- Run 1: 5m primary (max ~60 days from yfinance) ---
    print("\n[1/2] Fetching 5m data...")
    qqq_5m = fetch_bars("QQQ", args.start, args.end, interval="5m",
                        force_refresh=args.refresh)
    spy_5m = fetch_bars("SPY", args.start, args.end, interval="5m",
                        force_refresh=args.refresh)

    if qqq_5m:
        first = datetime.fromtimestamp(qqq_5m[0].timestamp_ms / 1000, tz=timezone.utc)
        last = datetime.fromtimestamp(qqq_5m[-1].timestamp_ms / 1000, tz=timezone.utc)
        print(f"\n  QQQ 5m range: {first.strftime('%Y-%m-%d')} → {last.strftime('%Y-%m-%d')} "
              f"({len(qqq_5m):,} bars)")
        print(f"  SPY 5m range: {len(spy_5m):,} bars")
        print("  Running 5m backtest...")
        results["5m"] = run_backtest(qqq_5m, spy_5m, args.capital, label="5m")
    else:
        print("  No 5m data available.")

    # --- Run 2: 1h extended (full 6-month range) ---
    print("\n[2/2] Fetching 1h data (full range)...")
    qqq_1h = fetch_bars("QQQ", args.start, args.end, interval="1h",
                        force_refresh=args.refresh)
    spy_1h = fetch_bars("SPY", args.start, args.end, interval="1h",
                        force_refresh=args.refresh)

    if qqq_1h:
        first = datetime.fromtimestamp(qqq_1h[0].timestamp_ms / 1000, tz=timezone.utc)
        last = datetime.fromtimestamp(qqq_1h[-1].timestamp_ms / 1000, tz=timezone.utc)
        print(f"\n  QQQ 1h range: {first.strftime('%Y-%m-%d')} → {last.strftime('%Y-%m-%d')} "
              f"({len(qqq_1h):,} bars)")
        print(f"  SPY 1h range: {len(spy_1h):,} bars")
        print("  Running 1h extended backtest...")
        results["1h (6-month)"] = run_backtest(qqq_1h, spy_1h, args.capital, label="1h")
    else:
        print("  No 1h data available.")

    if not results:
        print("\nERROR: No data fetched. Check network or API credentials.")
        sys.exit(1)

    # Write combined report
    write_report(results, args.start, args.end, args.capital)


if __name__ == "__main__":
    main()
