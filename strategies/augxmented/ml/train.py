#!/usr/bin/env python3
"""
ML Regime Filter — Training Pipeline
========================================
Runs the backtester in feature-collection mode, labels trades as
win (1) or loss (0), trains a Random Forest, and saves the model.

Usage:
    cd ~/trading-bot/kronos-trading
    python -m strategies.augxmented.ml.train
    python -m strategies.augxmented.ml.train --min-score 12  # expand training set
"""

import argparse
import sys
import json
import numpy as np
from pathlib import Path
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT.parent / ".env")

from strategies.templates.base_strategy import CandleData, Signal
from strategies.augxmented.strategy import AugxmentedStrategy
from strategies.augxmented.backtester.fetch_data import fetch_bars
from strategies.augxmented.ml.features import extract_features, FEATURE_NAMES
from strategies.augxmented.ml.regime_filter import RegimeFilter
from strategies.augxmented.timeframe import aggregate_candles
from strategies.augxmented.confluences.structure import detect_structure
from strategies.augxmented.config import WEIGHTS


def collect_training_data(
    qqq_candles: list[CandleData],
    spy_candles: list[CandleData],
    min_score: int = 12,
    label: str = "5m",
) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    """
    Run strategy with feature collection. For every entry signal that
    passes score >= min_score, extract features and track trade outcome.

    Returns (X, y, trade_info) where:
      X: feature matrix (n_trades, n_features)
      y: labels (1=win, 0=loss)
      trade_info: list of dicts with trade details
    """
    if not qqq_candles:
        return np.array([]), np.array([]), []

    spy_by_ts = {c.timestamp_ms: c for c in spy_candles}
    spy_timestamps = sorted(spy_by_ts.keys())

    strategy = AugxmentedStrategy()
    # Use lower score threshold to capture more training samples
    strategy.set_param('min_score', min_score)
    if label == "1h":
        strategy.set_param("min_history", 50)
        strategy.set_param("max_hold_bars", 8)
        strategy.set_param("cooldown_bars", 1)
    strategy.on_init()

    # State tracking
    features_list = []
    trade_outcomes = []
    trade_infos = []
    pending_feature = None  # feature vec waiting for trade outcome
    pending_info = None
    position = None  # (side, entry_price, entry_time)
    spy_history = []
    spy_ts_idx = 0

    for i, candle in enumerate(qqq_candles):
        # Update SPY history
        while spy_ts_idx < len(spy_timestamps) and spy_timestamps[spy_ts_idx] <= candle.timestamp_ms:
            spy_history.append(spy_by_ts[spy_timestamps[spy_ts_idx]])
            spy_ts_idx += 1
        if len(spy_history) > 200:
            spy_history = spy_history[-200:]
        strategy._spy_candles = spy_history

        strategy._update_history(candle)
        signal = strategy.on_candle(candle)

        if signal is None or signal.direction is None:
            continue

        if signal.direction == 0:
            # Exit — record outcome
            if position is not None and pending_feature is not None:
                side, entry_price, entry_time = position
                sign = 1 if side == "long" else -1
                pnl_pct = sign * (candle.close - entry_price) / entry_price * 100
                win = 1 if pnl_pct > 0 else 0
                features_list.append(pending_feature)
                trade_outcomes.append(win)
                pending_info['pnl_pct'] = pnl_pct
                pending_info['exit_tag'] = signal.tag
                pending_info['win'] = win
                trade_infos.append(pending_info)
                pending_feature = None
                pending_info = None
                position = None

        elif signal.direction in (1, -1):
            # Close existing position if flipping
            if position is not None and pending_feature is not None:
                side, entry_price, entry_time = position
                sign = 1 if side == "long" else -1
                pnl_pct = sign * (candle.close - entry_price) / entry_price * 100
                win = 1 if pnl_pct > 0 else 0
                features_list.append(pending_feature)
                trade_outcomes.append(win)
                pending_info['pnl_pct'] = pnl_pct
                pending_info['exit_tag'] = 'flip'
                pending_info['win'] = win
                trade_infos.append(pending_info)

            # Extract features for the new entry
            metadata = signal.metadata or {}
            breakdown = metadata.get('breakdown', {})
            total_score = metadata.get('score', 0)
            atr = metadata.get('atr', 0.0)

            # Get HTF trends from candle history
            candles = strategy._candle_history
            candles_by_tf = {
                '1h': aggregate_candles(candles, '1h'),
                '4h': aggregate_candles(candles, '4h'),
            }
            htf_1h = detect_structure(candles_by_tf.get('1h', []))
            htf_4h = detect_structure(candles_by_tf.get('4h', []))

            feat = extract_features(
                candles=candles,
                direction=signal.direction,
                current_atr=atr,
                breakdown=breakdown,
                total_score=total_score,
                htf_1h_trend=htf_1h['trend'],
                htf_4h_trend=htf_4h['trend'],
                timestamp_ms=candle.timestamp_ms,
            )
            pending_feature = feat
            pending_info = {
                'bar_index': i,
                'timestamp': candle.timestamp_ms,
                'direction': signal.direction,
                'score': total_score,
                'entry_price': candle.close,
                'atr': atr,
            }
            side = "long" if signal.direction == 1 else "short"
            position = (side, candle.close, candle.timestamp_ms)

    # Close any open position at end of data
    if position is not None and pending_feature is not None:
        side, entry_price, entry_time = position
        last = qqq_candles[-1]
        sign = 1 if side == "long" else -1
        pnl_pct = sign * (last.close - entry_price) / entry_price * 100
        win = 1 if pnl_pct > 0 else 0
        features_list.append(pending_feature)
        trade_outcomes.append(win)
        pending_info['pnl_pct'] = pnl_pct
        pending_info['exit_tag'] = 'end_of_data'
        pending_info['win'] = win
        trade_infos.append(pending_info)

    if not features_list:
        return np.array([]), np.array([]), []

    X = np.array(features_list)
    y = np.array(trade_outcomes)
    return X, y, trade_infos


def main():
    parser = argparse.ArgumentParser(description="Train ML Regime Filter")
    parser.add_argument("--min-score", type=int, default=12,
                        help="Min score threshold for training data (default: 12, lower = more samples)")
    parser.add_argument("--start", default="2025-09-25")
    parser.add_argument("--end", default="2026-03-25")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    print("=" * 60)
    print("  ML REGIME FILTER — TRAINING")
    print("=" * 60)
    print(f"  Min score for training: {args.min_score}")
    print(f"  Period: {args.start} -> {args.end}")
    print("-" * 60)

    # Fetch data (same as backtester)
    print("\n[1/4] Fetching data...")
    qqq_5m = fetch_bars("QQQ", args.start, args.end, interval="5m")
    spy_5m = fetch_bars("SPY", args.start, args.end, interval="5m")
    qqq_1h = fetch_bars("QQQ", args.start, args.end, interval="1h")
    spy_1h = fetch_bars("SPY", args.start, args.end, interval="1h")

    # Collect training data from both timeframes
    print("\n[2/4] Collecting training data...")
    all_X = []
    all_y = []
    all_info = []

    if qqq_5m:
        print(f"  Running 5m collection ({len(qqq_5m):,} bars)...")
        X_5m, y_5m, info_5m = collect_training_data(qqq_5m, spy_5m, args.min_score, "5m")
        if len(X_5m) > 0:
            all_X.append(X_5m)
            all_y.append(y_5m)
            all_info.extend(info_5m)
            print(f"    5m: {len(y_5m)} trades ({int(np.sum(y_5m))} wins, "
                  f"{len(y_5m) - int(np.sum(y_5m))} losses)")

    if qqq_1h:
        print(f"  Running 1h collection ({len(qqq_1h):,} bars)...")
        X_1h, y_1h, info_1h = collect_training_data(qqq_1h, spy_1h, args.min_score, "1h")
        if len(X_1h) > 0:
            all_X.append(X_1h)
            all_y.append(y_1h)
            all_info.extend(info_1h)
            print(f"    1h: {len(y_1h)} trades ({int(np.sum(y_1h))} wins, "
                  f"{len(y_1h) - int(np.sum(y_1h))} losses)")

    if not all_X:
        print("\nERROR: No training data collected. Check data availability.")
        sys.exit(1)

    X = np.concatenate(all_X, axis=0)
    y = np.concatenate(all_y, axis=0)
    print(f"\n  Total training set: {len(y)} trades "
          f"({int(np.sum(y))} wins, {len(y) - int(np.sum(y))} losses)")

    # Train model
    print("\n[3/4] Training Random Forest...")
    rf = RegimeFilter()
    metrics = rf.train(X, y)

    print(f"\n  Training Results:")
    print(f"    LOO Accuracy:          {metrics['loo_accuracy']:.1%}")
    print(f"    Avg P(win) for wins:   {metrics['avg_win_prob_for_wins']:.3f}")
    print(f"    Avg P(win) for losses: {metrics['avg_win_prob_for_losses']:.3f}")
    print(f"    Separation:            {metrics['avg_win_prob_for_wins'] - metrics['avg_win_prob_for_losses']:.3f}")

    print(f"\n  Feature Importances:")
    importances = metrics['feature_importances']
    for feat, imp in sorted(importances.items(), key=lambda x: -x[1]):
        bar = "#" * int(imp * 50)
        print(f"    {feat:20s} {imp:.3f}  {bar}")

    # Save model
    print("\n[4/4] Saving model...")
    rf.save()
    print(f"  Model saved: {rf._model_path}")

    # Save training metadata
    meta_path = rf._model_path.parent / "training_meta.json"
    meta = {
        'trained_at': datetime.now().isoformat(),
        'n_samples': int(metrics['n_samples']),
        'n_wins': int(metrics['n_wins']),
        'n_losses': int(metrics['n_losses']),
        'loo_accuracy': float(metrics['loo_accuracy']),
        'avg_win_prob_wins': float(metrics['avg_win_prob_for_wins']),
        'avg_win_prob_losses': float(metrics['avg_win_prob_for_losses']),
        'min_score_threshold': args.min_score,
        'data_period': f"{args.start} -> {args.end}",
        'feature_importances': {k: float(v) for k, v in importances.items()},
    }
    meta_path.write_text(json.dumps(meta, indent=2))
    print(f"  Metadata saved: {meta_path}")

    # Simulate filter impact at 0.65 threshold
    print(f"\n{'='*60}")
    print(f"  FILTER SIMULATION (threshold=0.65)")
    print(f"{'='*60}")
    probs = np.array([rf.predict_proba(x) for x in X])
    passed = probs >= 0.65
    n_passed = np.sum(passed)
    n_filtered = len(y) - n_passed

    if n_passed > 0:
        filtered_wr = np.mean(y[passed]) * 100
        original_wr = np.mean(y) * 100
        print(f"  Original:  {len(y)} trades, WR {original_wr:.1f}%")
        print(f"  Filtered:  {n_passed} trades, WR {filtered_wr:.1f}% ({n_filtered} filtered out)")
        print(f"  WR Change: {filtered_wr - original_wr:+.1f}%")
    else:
        print(f"  All {len(y)} trades would be filtered (threshold too aggressive)")


if __name__ == "__main__":
    main()
