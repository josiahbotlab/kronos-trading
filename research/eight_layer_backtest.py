#!/usr/bin/env python3
"""
Eight Layer Confluence Backtest — RBI step 2.

Loads BTC-USD 5-minute candles from the Kronos prices.db (schema differs
slightly from the original Moon Dev spec; columns are
  symbol, timeframe, timestamp_ms, timestamp_utc, open, high, low, close, volume
and timeframe label is '5m').

Reports:
  - whole-window stats: trades, WR, PF, total return, exit breakdown
  - score distribution at entry (winners vs losers)
  - 6+/8 sweep (does requiring stricter agreement help?)
  - IS/OOS split: train on first 60 days, test on last 30 days

Outputs trades CSV to research/eight_layer_backtest_results.csv.

Pass criteria: PF > 1.3 AND WR > 55% on OOS — only then proceed to RBI step
3 (robustness suite). NOT a deploy gate; tournament is the next step.

This script does not import or modify any live engine code.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
from strategies.eight_layer_confluence import (  # noqa: E402
    generate_signals, MIN_LAYERS, ATR_SL_MULT, ATR_TP_MULT,
)

DB_DEFAULT = ROOT / "data" / "prices.db"
RESULTS_CSV = HERE / "eight_layer_backtest_results.csv"
MAX_HOLD_BARS = 288  # 24h at 5m bars


def load_btc(db_path: Path, symbol: str = "BTC-USD",
             timeframe: str = "5m", days: int = 180) -> pd.DataFrame:
    """Pull last `days` of OHLCV. Returns DataFrame indexed by UTC timestamp."""
    conn = sqlite3.connect(db_path)
    df = pd.read_sql(
        """
        SELECT timestamp_utc, open, high, low, close, volume
        FROM ohlcv
        WHERE symbol=? AND timeframe=?
        ORDER BY timestamp_ms ASC
        """,
        conn, params=(symbol, timeframe),
    )
    conn.close()
    if df.empty:
        return df
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    df = df.set_index("timestamp_utc")
    if days:
        cutoff = df.index.max() - pd.Timedelta(days=days)
        df = df.loc[df.index >= cutoff]
    return df


# =============================================================================
# Backtest engine — bar-level walk, SL/TP/max-hold exits.
# =============================================================================
def _check_exit(direction: int, sl: float, tp: float, row,
                bars_held: int) -> tuple[bool, str, float]:
    """Return (hit, reason, exit_price). Pessimistic when both SL and TP fall
    inside the same bar (treats SL as hit)."""
    high, low = row["high"], row["low"]
    if direction == 1:
        hit_sl = low <= sl
        hit_tp = high >= tp
    else:
        hit_sl = high >= sl
        hit_tp = low <= tp
    if hit_sl and hit_tp:
        return True, "SL", sl  # pessimistic
    if hit_sl:
        return True, "SL", sl
    if hit_tp:
        return True, "TP", tp
    if bars_held >= MAX_HOLD_BARS:
        return True, "MAX_HOLD", row["close"]
    return False, "", 0.0


def run_backtest(df: pd.DataFrame, min_layers: int = MIN_LAYERS) -> pd.DataFrame:
    """Bar-by-bar walk, single position at a time, signal on close, fill on
    next bar's open (avoids look-ahead). Exit triggered intra-bar."""
    sig = generate_signals(df, min_layers=min_layers)
    sig = sig.reset_index().rename(columns={"timestamp_utc": "ts"})
    n = len(sig)
    in_trade = False
    entry_price = 0.0
    entry_idx = 0
    direction = 0
    sl = tp = 0.0
    long_score_at_entry = 0
    short_score_at_entry = 0
    trades = []

    for i in range(n - 1):  # need i+1 to fill on next bar's open
        row = sig.iloc[i]
        if in_trade:
            hit, reason, exit_price = _check_exit(
                direction, sl, tp, row, i - entry_idx,
            )
            if hit:
                pnl_pct = ((exit_price - entry_price) / entry_price) * direction * 100.0
                trades.append({
                    "entry_ts": sig["ts"].iloc[entry_idx],
                    "exit_ts": sig["ts"].iloc[i],
                    "direction": "LONG" if direction == 1 else "SHORT",
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "pnl_pct": pnl_pct,
                    "exit_reason": reason,
                    "bars_held": i - entry_idx,
                    "long_score": long_score_at_entry,
                    "short_score": short_score_at_entry,
                })
                in_trade = False

        if not in_trade and row["signal"] != 0:
            # Fill at next bar's open (look-ahead-safe)
            next_open = sig.iloc[i + 1]["open"]
            atr_row = row["atr"]
            if pd.isna(atr_row) or pd.isna(next_open):
                continue
            entry_price = next_open
            direction = int(row["signal"])
            entry_idx = i + 1
            if direction == 1:
                sl = entry_price - ATR_SL_MULT * atr_row
                tp = entry_price + ATR_TP_MULT * atr_row
            else:
                sl = entry_price + ATR_SL_MULT * atr_row
                tp = entry_price - ATR_TP_MULT * atr_row
            long_score_at_entry = int(row["long_score"])
            short_score_at_entry = int(row["short_score"])
            in_trade = True

    return pd.DataFrame(trades)


# =============================================================================
# Reporting
# =============================================================================
def metrics(trades: pd.DataFrame) -> dict:
    if trades.empty:
        return {"trades": 0}
    wins = trades["pnl_pct"] > 0
    losers = ~wins
    avg_win = trades.loc[wins, "pnl_pct"].mean() if wins.any() else 0.0
    avg_loss = trades.loc[losers, "pnl_pct"].mean() if losers.any() else 0.0
    gross_win = trades.loc[wins, "pnl_pct"].sum()
    gross_loss = trades.loc[losers, "pnl_pct"].sum()
    pf = abs(gross_win / gross_loss) if gross_loss != 0 else float("inf")
    return {
        "trades": int(len(trades)),
        "win_rate_pct": round(100.0 * wins.mean(), 2),
        "total_return_pct": round(trades["pnl_pct"].sum(), 2),
        "profit_factor": round(pf, 3),
        "avg_win_pct": round(avg_win, 3),
        "avg_loss_pct": round(avg_loss, 3),
        "longs": int((trades["direction"] == "LONG").sum()),
        "shorts": int((trades["direction"] == "SHORT").sum()),
    }


def fmt_metrics(label: str, m: dict) -> str:
    if m.get("trades", 0) == 0:
        return f"  {label}: NO TRADES"
    return (
        f"  {label}: trades={m['trades']:<4d} "
        f"WR={m['win_rate_pct']:>5.1f}%  PF={m['profit_factor']:>5.2f}  "
        f"ret={m['total_return_pct']:>+7.2f}%  "
        f"avgW={m['avg_win_pct']:>+5.2f}% avgL={m['avg_loss_pct']:>+5.2f}%  "
        f"L/S={m['longs']}/{m['shorts']}"
    )


def split_is_oos(df: pd.DataFrame, is_days: int = 60,
                  oos_days: int = 30) -> tuple[pd.DataFrame, pd.DataFrame]:
    end = df.index.max()
    oos_start = end - pd.Timedelta(days=oos_days)
    is_start = oos_start - pd.Timedelta(days=is_days)
    is_df = df.loc[(df.index >= is_start) & (df.index < oos_start)]
    oos_df = df.loc[df.index >= oos_start]
    return is_df, oos_df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DB_DEFAULT))
    ap.add_argument("--symbol", default="BTC-USD")
    ap.add_argument("--timeframe", default="5m")
    ap.add_argument("--days", type=int, default=120)
    args = ap.parse_args()

    print("=" * 70)
    print("Eight Layer Confluence — Backtest")
    print("=" * 70)
    print(f"DB:        {args.db}")
    print(f"Symbol:    {args.symbol} {args.timeframe}")

    df = load_btc(Path(args.db), args.symbol, args.timeframe, days=args.days)
    if df.empty:
        print("ERROR: no OHLCV rows loaded — check schema/symbol/timeframe.")
        sys.exit(2)
    print(f"Window:    {df.index.min()}  ->  {df.index.max()}")
    print(f"Candles:   {len(df):,}")
    print()

    # ---- Whole-window run with default 5+/8 ---------------------------------
    print(f"--- Whole window  (min_layers={MIN_LAYERS}) ---")
    trades_5 = run_backtest(df, min_layers=MIN_LAYERS)
    m5 = metrics(trades_5)
    print(fmt_metrics(f"5+ /8 ", m5))
    if not trades_5.empty:
        # Average layer agreement on winners vs losers
        wins = trades_5[trades_5["pnl_pct"] > 0]
        loss = trades_5[trades_5["pnl_pct"] <= 0]
        long_wins = wins[wins["direction"] == "LONG"]
        long_loss = loss[loss["direction"] == "LONG"]
        short_wins = wins[wins["direction"] == "SHORT"]
        short_loss = loss[loss["direction"] == "SHORT"]
        print(f"  Avg LONG score:   wins {long_wins['long_score'].mean():.2f}  "
              f"losers {long_loss['long_score'].mean():.2f}  "
              f"(n={len(long_wins)} / {len(long_loss)})")
        print(f"  Avg SHORT score:  wins {short_wins['short_score'].mean():.2f}  "
              f"losers {short_loss['short_score'].mean():.2f}  "
              f"(n={len(short_wins)} / {len(short_loss)})")
        print(f"  Exit breakdown:")
        for k, v in trades_5["exit_reason"].value_counts().items():
            print(f"    {k:10s} {v}")
    print()

    # ---- 6+/8 stricter sweep -----------------------------------------------
    print("--- Stricter agreement sweep ---")
    for ml in (5, 6, 7):
        t = run_backtest(df, min_layers=ml)
        print(fmt_metrics(f"{ml}+/8 ", metrics(t)))
    print()

    # ---- IS/OOS 60/30 split -------------------------------------------------
    is_df, oos_df = split_is_oos(df, is_days=60, oos_days=30)
    print(f"--- IS/OOS split (IS=60d, OOS=30d) ---")
    print(f"  IS:  {is_df.index.min()}  ->  {is_df.index.max()}  ({len(is_df):,} bars)")
    print(f"  OOS: {oos_df.index.min()} ->  {oos_df.index.max()} ({len(oos_df):,} bars)")
    is_trades = run_backtest(is_df, min_layers=MIN_LAYERS)
    oos_trades = run_backtest(oos_df, min_layers=MIN_LAYERS)
    m_is = metrics(is_trades)
    m_oos = metrics(oos_trades)
    print(fmt_metrics("IS  ", m_is))
    print(fmt_metrics("OOS ", m_oos))
    print()

    # ---- Pass/fail verdict --------------------------------------------------
    pf_oos = m_oos.get("profit_factor", 0)
    wr_oos = m_oos.get("win_rate_pct", 0)
    n_oos = m_oos.get("trades", 0)
    pass_pf = pf_oos > 1.3
    pass_wr = wr_oos > 55.0
    pass_n = n_oos >= 30
    verdict = ("PASS — proceed to RBI step 3 (robustness suite)"
               if (pass_pf and pass_wr and pass_n)
               else "FAIL — incubation candidate, revisit with more data")
    print("=" * 70)
    print("Verdict:")
    print(f"  PF_oos > 1.3   : {pf_oos}  -> {'PASS' if pass_pf else 'FAIL'}")
    print(f"  WR_oos > 55%   : {wr_oos}% -> {'PASS' if pass_wr else 'FAIL'}")
    print(f"  N_oos  >= 30   : {n_oos}    -> {'PASS' if pass_n else 'FAIL (insufficient sample)'}")
    print(f"  -> {verdict}")
    print("=" * 70)

    # Save full whole-window trade list
    if not trades_5.empty:
        trades_5.to_csv(RESULTS_CSV, index=False)
        print(f"trades CSV: {RESULTS_CSV}")


if __name__ == "__main__":
    main()
