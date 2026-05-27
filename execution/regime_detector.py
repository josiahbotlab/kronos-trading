#!/usr/bin/env python3
"""
Kronos Regime Detector
========================
Classifies market regime from in-memory candle history.
No DB queries. Uses OHLCV data already on CandleData objects.

Regimes:
  trending_up   - SMA20 > SMA50, close above both, ATR normal
  trending_down - SMA20 < SMA50, close below both, ATR normal
  ranging       - SMAs interleaved, price oscillating around them
  volatile      - ATR > 2x its longer-term average

Used by TradeJournal to tag trades with market context at entry/exit.
"""

import numpy as np

# Import CandleData type for annotation
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from strategies.templates.base_strategy import CandleData

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MIN_CANDLES = 50
SMA_FAST_PERIOD = 20
SMA_SLOW_PERIOD = 50
ATR_PERIOD = 14
ATR_LONG_PERIOD = 50
ATR_VOLATILE_MULT = 2.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def detect_regime(candles: list) -> str:
    """
    Classify current market regime from candle history.

    Args:
        candles: List of CandleData, oldest first. Needs >= 50 candles.

    Returns:
        One of: "trending_up", "trending_down", "ranging", "volatile", "unknown"
    """
    if not candles or len(candles) < MIN_CANDLES:
        return "unknown"

    closes = np.array([c.close for c in candles])

    # Volatility check first (overrides trend classification)
    atr_ratio = _compute_atr_ratio(candles)
    if atr_ratio > ATR_VOLATILE_MULT:
        return "volatile"

    # Trend classification via SMA crossover
    sma_fast = float(np.mean(closes[-SMA_FAST_PERIOD:]))
    sma_slow = float(np.mean(closes[-SMA_SLOW_PERIOD:]))
    current_close = float(closes[-1])

    if current_close > sma_fast > sma_slow:
        return "trending_up"
    if current_close < sma_fast < sma_slow:
        return "trending_down"

    return "ranging"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _compute_atr(candles: list, period: int) -> float:
    """Average True Range over last  candles."""
    if len(candles) < period + 1:
        return 0.0

    trs = []
    recent = candles[-(period + 1):]
    for i in range(1, len(recent)):
        high = recent[i].high
        low = recent[i].low
        prev_close = recent[i - 1].close
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    return float(np.mean(trs[-period:])) if trs else 0.0


def _compute_atr_ratio(candles: list) -> float:
    """Current ATR(14) divided by longer-term ATR(50). >2.0 = volatile."""
    if len(candles) < ATR_LONG_PERIOD + 1:
        return 1.0  # not enough data, assume normal

    atr_short = _compute_atr(candles, ATR_PERIOD)
    atr_long = _compute_atr(candles, ATR_LONG_PERIOD)

    if atr_long < 1e-8:
        return 1.0
    return atr_short / atr_long
