#!/usr/bin/env python3
"""
Moon Dev Strategy Tournament — Phase 2/3
=========================================
Runs all 136 OHLCV-only strategies against 6-month BTC 1m data.

Split:
  - In-sample (IS): 2025-11-01 to 2026-03-31 (~5 months)
  - Out-of-sample (OOS): 2026-04-01 to 2026-04-30 (~30 days)

Pass criteria (locked):
  - >= 100 trades
  - Win rate >= 52%
  - Profit factor >= 1.2
  - Max drawdown reported

Additions:
  - WR 95% CI lower bound via Beta distribution
  - Pre-filter: skip if IS trades < 50

Output:
  - results_is.csv — in-sample metrics per strategy
  - results_oos.csv — out-of-sample metrics per strategy
  - tournament_log.txt — detailed run log
"""

import csv
import importlib
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# Project root
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from strategies.templates.base_strategy import BaseStrategy, CandleData, Signal

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PARQUET_PATH = PROJECT_ROOT / "research" / "btc_multiagent" / "data" / "btc_1m_6months.parquet"
OUTPUT_DIR = Path(__file__).parent
FEE_RATE = 0.0006       # 0.06% taker
INITIAL_CAPITAL = 10000.0
LEVERAGE = 1.0
MIN_IS_TRADES = 50       # Pre-filter: skip if IS trades < 50

# IS/OOS split boundary (unix ms)
IS_END = int(datetime(2026, 4, 1, tzinfo=timezone.utc).timestamp() * 1000)

# OHLCV-only strategy files (from inventory)
OHLCV_STRATEGIES = [
    "adaptive_trend_with_kaufman_moving_avera",
    "adx_macd_momentum",
    "adx_rising_macd",
    "adx_trend_vs_chop_classification",
    "aggressive_maker_order_management",
    "ai_swarm_long_only_dip_entry",
    "ai_swarm_whale_following_on_polymarket",
    "airdrop_volume_farming_via_high_leverage",
    "atr_stop_hunt_counter_trade",
    "bb_adx_trend_breakout",
    "bb_squeeze_adx",
    "bb_squeeze_breakout",
    "bollinger_band_mean_reversion",
    "bollinger_band_sma_bounce",
    "bollinger_bands_capitulation_filter",
    "consecutive_bars_reversal",
    "consecutive_down_reversal",
    "consolidation_breakout",
    "copy_trading_with_sma_trend_filter",
    "cricket_ipl_psl_stink_bid_bot",
    "cross_exchange_delta_neutral_arbitrage",
    "dca_pop",
    "direction_strength_speed_to_fill_scalpin",
    "dual_sma_trend_following_with_pullback_e",
    "edge_market_time_arbitrage",
    "end_of_period_close_bot",
    "gap_go_uo",
    "gradual_position_exit",
    "graduated_position_sizing",
    "hidden_markov_model_regime_detection",
    "housecoin_100x_smart_accumulation_bot",
    "intraday_bollinger_with_adx_confirmation",
    "intraday_parabolic_short",
    "iv_surface_reconstruction",
    "kalman_bb_breakout",
    "kalman_filter_enhancement_layer",
    "kalshi_whale_scanner",
    "macd_6_25_high_threshold_momentum",
    "macd_ema_crossover",
    "market_regime_based_strategy_selection",
    "markov_down_bars",
    "mean_reversion_algorithm_with_fixed_risk",
    "mean_reversion_bot",
    "mean_reversion_market_maker",
    "mean_reversion_multi_timeframe",
    "mtf_mean_reversion",
    "multi_timeframe_mean_reversion",
    "nba_first_half_stink_bid_bot",
    "no_fade_whale_bot",
    "obv_capitulation_divergence",
    "ofi_machine_learning_binary_classifier",
    "optimized_sma_pullback",
    "parabolic_short",
    "qqe_rsi_multi_indicator_system",
    "rbi_framework",
    "rbi_incubation_risk_management_protocol",
    "regular_classic_two_leg_statistical_arbi",
    "research_125_vwap_momentum",
    "research_135_20_40_sma_crossover_with_5_day_hold",
    "research_141_exhaustion_gap_strategy",
    "research_150_dca_bot_with_sma_filter",
    "research_158_solana_early_launch_sniping",
    "research_171_oscillating_crossover",
    "research_182_supply_and_demand_wick_range",
    "research_205_solana_new_token_sniper",
    "research_206_small_cap_meme_momentum_filter",
    "research_207_kalman_filter_bollinger_band_breakout",
    "research_208_kalman_mean_reversion_sniper",
    "research_209_kalman_momentum_killer",
    "research_213_waddah_attar_explosion_adx_hybrid",
    "research_219_supply_and_demand_zone_bot_with_trend_fi",
    "research_22_md_momentum",
    "research_242_dual_moving_average_crossover",
    "research_244_donchian_channel_breakout",
    "research_245_rsi_moving_average_confluence",
    "research_246_bollinger_band_trend_following",
    "research_247_macd_adx_trend_confirmation",
    "research_248_volume_confirmed_trend_following",
    "research_249_short_term_ma_crossover",
    "research_250_intraday_bollinger_bands_with_adx",
    "research_253_volatility_adjusted_signal_thresholds",
    "research_254_kaufman_adaptive_moving_average",
    "research_267_tick_optimized_limit_execution",
    "research_277_ab_cd_harmonic_pattern",
    "research_28_smart_dca_with_sma_volume_filtering",
    "research_310_supply_and_demand_zones",
    "research_324_multi_exchange_lagger_detection_momentum",
    "research_343_sellers_exhaustion_volume_wick",
    "research_344_consecutive_down_closes_mean_reversion",
    "research_359_sma_crossover_strategy",
    "research_360_long_only_sma_price_cross",
    "research_362_sma_with_kalman_filter",
    "research_368_two_down_bars_median_reversion",
    "research_40_capitulation_dip_buying",
    "research_58_solana_new_token_sniper",
    "research_78_smart_money_stop_hunt",
    "research_86_rsi_divergence_multi_indicator_strategy",
    "research_87_macd_momentum_crossover",
    "research_96_solana_micro_cap_new_token_sniper",
    "rsi_enhanced_bollinger_bands",
    "rsi_extremes",
    "sma_fibonacci_confluence_long",
    "sma_long_only_price_cross",
    "sma_pullback_with_previous_day_low",
    "sma_trend_filter",
    "sma_trend_following",
    "smi_momentum_divergence",
    "solana_meme_coin_sniper_bot",
    "solana_new_token_sniper",
    "solana_trending_token_scanner",
    "statistical_arbitrage",
    "statistical_arbitrage_supply_demand_zone",
    "statistical_arbitrage_z_score",
    "strict_risk_controlled_position_sizing",
    "supply_and_demand_wick_range",
    "supply_and_demand_zone_bot",
    "supply_demand_zone_mean_reversion",
    "t_copula_fat_tail_statistical_arbitrage",
    "time_weighted_dollar_cost_averaging_entr",
    "timeality",
    "trend_following_with_order_flow_confirma",
    "two_down_bars_median_price_reversion",
    "uncorrelated_multi_strategy_portfolio",
    "volume_based_dynamic_exit",
    "volume_weighted_feature_engineering",
    "vwap_adx_trend",
    "vwap_double_stochastic",
    "vwap_extreme_mean_reversion",
    "vwap_mean_reversion",
    "weekly_low_accumulation",
    "whale_copy_trading_bot",
    "whale_sweep_following",
    "whale_sweep_following_with_quality_filte",
    "wta_tennis_stink_bid_bot",
    "zscore_stat_arb",
]

# Also test sma_crossover from momentum/
EXTRA_STRATEGIES = [
    ("strategies.momentum.sma_crossover", "SMACrossover"),
]


# ---------------------------------------------------------------------------
# Position tracker (mirrors core/backtester.py logic)
# ---------------------------------------------------------------------------
@dataclass
class Position:
    side: str
    entry_price: float
    entry_time: int
    quantity: float
    tag: str = ""


@dataclass
class TradeRecord:
    entry_time: int
    exit_time: int
    side: str
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    pnl_pct: float
    fees: float
    tag: str = ""


def run_backtest(strategy_cls, candles, initial_capital=INITIAL_CAPITAL):
    """Run a single strategy against a list of CandleData. Returns list of TradeRecord."""
    strategy = strategy_cls()
    strategy.on_init()

    position = None
    equity = initial_capital
    trades = []

    for candle in candles:
        strategy._update_history(candle)

        try:
            signal = strategy.on_candle(candle)
        except Exception:
            continue

        if signal is None or not isinstance(signal, Signal):
            continue
        if signal.direction is None:
            continue

        if signal.direction == 0:
            if position:
                trade, equity = _close(position, candle, equity)
                trades.append(trade)
                position = None
                try:
                    strategy.on_trade(trade.pnl, trade.pnl_pct)
                except Exception:
                    pass

        elif signal.direction == 1:
            if position and position.side == "short":
                trade, equity = _close(position, candle, equity)
                trades.append(trade)
                position = None
                try:
                    strategy.on_trade(trade.pnl, trade.pnl_pct)
                except Exception:
                    pass
            if not position:
                position, equity = _open("long", candle, signal, equity)

        elif signal.direction == -1:
            if position and position.side == "long":
                trade, equity = _close(position, candle, equity)
                trades.append(trade)
                position = None
                try:
                    strategy.on_trade(trade.pnl, trade.pnl_pct)
                except Exception:
                    pass
            if not position:
                position, equity = _open("short", candle, signal, equity)

    # Force close at end
    if position and candles:
        trade, equity = _close(position, candles[-1], equity)
        trades.append(trade)

    return trades


def _open(side, candle, signal, equity):
    price = candle.close
    strength = min(max(signal.strength, 0.0), 1.0) if signal.strength else 1.0
    notional = equity * LEVERAGE * strength
    if notional <= 0 or price <= 0:
        return None, equity
    quantity = notional / price
    fee = notional * FEE_RATE
    equity -= fee
    pos = Position(side=side, entry_price=price, entry_time=candle.timestamp_ms,
                   quantity=quantity, tag=signal.tag)
    return pos, equity


def _close(position, candle, equity):
    exit_price = candle.close
    if position.side == "long":
        pnl = (exit_price - position.entry_price) * position.quantity
    else:
        pnl = (position.entry_price - exit_price) * position.quantity

    cost_basis = position.entry_price * position.quantity
    pnl_pct = (pnl / cost_basis * 100) if cost_basis > 0 else 0.0

    notional = exit_price * position.quantity
    fee = notional * FEE_RATE
    pnl -= fee
    equity += pnl

    trade = TradeRecord(
        entry_time=position.entry_time,
        exit_time=candle.timestamp_ms,
        side=position.side,
        entry_price=position.entry_price,
        exit_price=exit_price,
        quantity=position.quantity,
        pnl=pnl,
        pnl_pct=pnl_pct,
        fees=fee * 2,
        tag=position.tag,
    )
    return trade, equity


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def compute_metrics(trades, initial_capital=INITIAL_CAPITAL):
    """Compute tournament metrics from trade list."""
    if not trades:
        return {}

    total = len(trades)
    winners = [t for t in trades if t.pnl > 0]
    losers = [t for t in trades if t.pnl <= 0]
    wins = len(winners)

    wr = wins / total * 100 if total > 0 else 0
    gross_profit = sum(t.pnl for t in winners) if winners else 0
    gross_loss = abs(sum(t.pnl for t in losers)) if losers else 0
    pf = gross_profit / gross_loss if gross_loss > 0 else float('inf')

    total_pnl = sum(t.pnl for t in trades)
    total_return_pct = total_pnl / initial_capital * 100

    # Max drawdown
    equity = initial_capital
    peak = equity
    max_dd_pct = 0.0
    for t in sorted(trades, key=lambda x: x.exit_time):
        equity += t.pnl
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100 if peak > 0 else 0
        if dd > max_dd_pct:
            max_dd_pct = dd

    # WR confidence interval (Beta distribution)
    wr_ci_lower = 0.0
    try:
        from scipy.stats import beta as beta_dist
        if total > 0:
            wr_ci_lower = beta_dist.ppf(0.025, wins + 0.5, total - wins + 0.5) * 100
    except ImportError:
        # Fallback: normal approximation
        if total > 0:
            p = wins / total
            se = (p * (1 - p) / total) ** 0.5
            wr_ci_lower = max(0, (p - 1.96 * se)) * 100

    # Avg holding time
    holding_mins = [(t.exit_time - t.entry_time) / 60000 for t in trades]
    avg_hold_min = np.mean(holding_mins) if holding_mins else 0

    # Sharpe
    pnl_pcts = [t.pnl_pct for t in trades]
    sharpe = 0.0
    if len(pnl_pcts) > 1:
        mean_r = np.mean(pnl_pcts)
        std_r = np.std(pnl_pcts, ddof=1)
        if std_r > 0:
            duration_days = (trades[-1].exit_time - trades[0].entry_time) / (1000 * 86400)
            tpy = len(trades) / (duration_days / 365.25) if duration_days > 0 else 252
            sharpe = (mean_r / std_r) * np.sqrt(tpy)

    return {
        "total_trades": total,
        "wins": wins,
        "losses": total - wins,
        "win_rate_pct": round(wr, 2),
        "wr_ci_lower_pct": round(wr_ci_lower, 2),
        "profit_factor": round(pf, 4) if pf != float('inf') else 9999.0,
        "total_pnl_usd": round(total_pnl, 2),
        "total_return_pct": round(total_return_pct, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "sharpe_ratio": round(sharpe, 2),
        "avg_hold_min": round(avg_hold_min, 1),
        "best_trade_pct": round(max(t.pnl_pct for t in trades), 2) if trades else 0,
        "worst_trade_pct": round(min(t.pnl_pct for t in trades), 2) if trades else 0,
    }


# ---------------------------------------------------------------------------
# Strategy loader
# ---------------------------------------------------------------------------
def load_strategy_class(module_name):
    """Import strategy module and find the BaseStrategy subclass."""
    mod = importlib.import_module(module_name)
    for attr_name in dir(mod):
        attr = getattr(mod, attr_name)
        if (isinstance(attr, type)
                and issubclass(attr, BaseStrategy)
                and attr is not BaseStrategy
                and hasattr(attr, 'on_candle')):
            return attr
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("=" * 70)
    print("  MOON DEV STRATEGY TOURNAMENT")
    print("=" * 70)
    start_time = time.time()

    # Load data
    print(f"\nLoading parquet: {PARQUET_PATH}")
    df = pd.read_parquet(PARQUET_PATH)
    print(f"  Rows: {len(df)}, Columns: {list(df.columns)}")

    # Convert to CandleData list
    print("  Converting to CandleData...")
    all_candles = []
    for _, row in df.iterrows():
        ts = row['timestamp']
        if hasattr(ts, 'timestamp'):
            ts_ms = int(ts.timestamp() * 1000)
        else:
            ts_ms = int(ts)
        all_candles.append(CandleData(
            timestamp_ms=ts_ms,
            open=float(row['open']),
            high=float(row['high']),
            low=float(row['low']),
            close=float(row['close']),
            volume=float(row['volume']),
        ))

    # Split IS / OOS
    is_candles = [c for c in all_candles if c.timestamp_ms < IS_END]
    oos_candles = [c for c in all_candles if c.timestamp_ms >= IS_END]
    print(f"  IS candles: {len(is_candles)} (to 2026-03-31)")
    print(f"  OOS candles: {len(oos_candles)} (2026-04-01 onward)")

    # Build strategy list
    strategies = []
    for name in OHLCV_STRATEGIES:
        strategies.append((f"strategies.generated.{name}", name))
    for mod_path, cls_name in EXTRA_STRATEGIES:
        strategies.append((mod_path, mod_path.split(".")[-1]))

    print(f"\n  Strategies to test: {len(strategies)}")
    print("-" * 70)

    # Results
    is_results = []
    oos_results = []
    log_lines = []

    def log(msg):
        print(msg)
        log_lines.append(msg)

    skipped_import = 0
    skipped_volume = 0
    tested = 0

    for i, (mod_path, name) in enumerate(strategies):
        prefix = f"[{i+1}/{len(strategies)}]"

        # Import
        try:
            cls = load_strategy_class(mod_path)
            if cls is None:
                log(f"{prefix} {name}: SKIP (no strategy class found)")
                skipped_import += 1
                continue
        except Exception as e:
            log(f"{prefix} {name}: IMPORT_ERROR ({str(e)[:60]})")
            skipped_import += 1
            continue

        # IS backtest
        try:
            is_trades = run_backtest(cls, is_candles)
        except Exception as e:
            log(f"{prefix} {name}: RUNTIME_ERROR IS ({str(e)[:60]})")
            is_results.append({"strategy": name, "status": "RUNTIME_ERROR",
                               "error": str(e)[:100]})
            continue

        is_count = len(is_trades)

        if is_count < MIN_IS_TRADES:
            log(f"{prefix} {name}: INSUFFICIENT_VOLUME (IS trades={is_count} < {MIN_IS_TRADES})")
            is_results.append({"strategy": name, "status": "INSUFFICIENT_VOLUME",
                               "total_trades": is_count})
            skipped_volume += 1
            continue

        is_metrics = compute_metrics(is_trades)
        is_metrics["strategy"] = name
        is_metrics["status"] = "TESTED"
        is_results.append(is_metrics)

        # OOS backtest
        try:
            oos_trades = run_backtest(cls, oos_candles)
        except Exception as e:
            log(f"{prefix} {name}: RUNTIME_ERROR OOS ({str(e)[:60]})")
            oos_results.append({"strategy": name, "status": "RUNTIME_ERROR",
                                "error": str(e)[:100]})
            tested += 1
            continue

        oos_count = len(oos_trades)
        if oos_count > 0:
            oos_metrics = compute_metrics(oos_trades)
        else:
            oos_metrics = {"total_trades": 0, "win_rate_pct": 0, "profit_factor": 0,
                           "max_drawdown_pct": 0, "total_return_pct": 0,
                           "wr_ci_lower_pct": 0, "sharpe_ratio": 0}
        oos_metrics["strategy"] = name
        oos_metrics["status"] = "TESTED"
        oos_results.append(oos_metrics)

        # Determine tier
        is_pass = (is_count >= 100
                   and is_metrics["win_rate_pct"] >= 52
                   and is_metrics["profit_factor"] >= 1.2)

        oos_pass = (oos_count >= 20  # proportional: ~100 trades / 5 months * 1 month = ~20
                    and oos_metrics.get("win_rate_pct", 0) >= 52
                    and oos_metrics.get("profit_factor", 0) >= 1.2)

        if is_pass and oos_pass:
            tier = "TIER1"
        elif is_pass:
            tier = "TIER2"
        else:
            tier = "TIER3"

        log(f"{prefix} {name}: {tier} | IS: {is_count}t WR={is_metrics['win_rate_pct']:.1f}% "
            f"PF={is_metrics['profit_factor']:.2f} DD={is_metrics['max_drawdown_pct']:.1f}% "
            f"| OOS: {oos_count}t WR={oos_metrics.get('win_rate_pct', 0):.1f}% "
            f"PF={oos_metrics.get('profit_factor', 0):.2f}")

        tested += 1

    # Summary
    elapsed = time.time() - start_time
    log(f"\n{'=' * 70}")
    log(f"TOURNAMENT COMPLETE — {elapsed:.0f}s")
    log(f"  Tested: {tested}")
    log(f"  Skipped (import error): {skipped_import}")
    log(f"  Skipped (insufficient volume): {skipped_volume}")
    log(f"{'=' * 70}")

    # Write CSVs
    _write_csv(OUTPUT_DIR / "results_is.csv", is_results)
    _write_csv(OUTPUT_DIR / "results_oos.csv", oos_results)

    # Write log
    with open(OUTPUT_DIR / "tournament_log.txt", "w") as f:
        f.write("\n".join(log_lines))

    print(f"\nResults written to:")
    print(f"  {OUTPUT_DIR / 'results_is.csv'}")
    print(f"  {OUTPUT_DIR / 'results_oos.csv'}")
    print(f"  {OUTPUT_DIR / 'tournament_log.txt'}")


def _write_csv(path, rows):
    if not rows:
        return
    keys = set()
    for r in rows:
        keys.update(r.keys())
    # Stable column order
    cols = ["strategy", "status"]
    for k in sorted(keys):
        if k not in cols:
            cols.append(k)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
