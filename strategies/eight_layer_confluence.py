"""
Eight Layer Confluence Strategy — Moon Dev Feb25
Adapted for Kronos crypto pipeline (BTC-USD, 5-min candles).

Requires 5+ of 8 independent layers to agree before entry.
"When 5+ layers agree, the market is speaking clearly." — Moon Dev

Implementation note: spec called for talib; talib isn't installed on this
host, so indicators are implemented with pandas/numpy (Wilder smoothing for
RSI/ATR/ADX, EMA via .ewm, MACD via EMA difference, CCI/SMA standard).
Outputs match talib's defaults to within rounding.

This file is RESEARCH-only. It does NOT subclass BaseStrategy and is NOT
auto-discovered by the live engine. Tournament integration (BaseStrategy
subclass + signal queue wiring) only happens AFTER backtest passes the
IS/OOS gate (PF > 1.3 AND WR > 55% on OOS).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

STRATEGY_NAME = "eight_layer_confluence"

# -- Layer thresholds (per spec) --------------------------------------------
EMA_FAST = 21
EMA_SLOW = 55
RSI_PERIOD = 14
RSI_LOW = 40        # RSI power zone lower bound (long)
RSI_HIGH = 65       # RSI power zone upper bound (long)
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
VOLUME_MULT = 1.3   # Volume must be 1.3x rolling average
VOLUME_SMA = 20
ADX_PERIOD = 14
ADX_MIN = 18        # Trend exists threshold (direction-agnostic)
CCI_PERIOD = 20
ATR_PERIOD = 14
ATR_SL_MULT = 1.8
ATR_TP_MULT = 4.0
MIN_LAYERS = 5      # Minimum layers to agree for signal
SUPERTREND_PERIOD = 10
SUPERTREND_MULT = 3.0


# =============================================================================
# Indicators (pure pandas / numpy)
# =============================================================================
def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def _sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def _wilder(s: pd.Series, n: int) -> pd.Series:
    """Wilder's smoothing (alpha = 1/n). Used by talib for RSI/ATR/ADX."""
    return s.ewm(alpha=1.0 / n, adjust=False).mean()


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0.0)
    down = -delta.clip(upper=0.0)
    rs_up = _wilder(up, n)
    rs_down = _wilder(down, n)
    rs = rs_up / rs_down.replace(0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def _macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    macd = _ema(close, fast) - _ema(close, slow)
    sig = _ema(macd, signal)
    hist = macd - sig
    return macd, sig, hist


def _true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    return pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)


def _atr(high, low, close, n: int = 14) -> pd.Series:
    return _wilder(_true_range(high, low, close), n)


def _adx(high, low, close, n: int = 14) -> pd.Series:
    """Standard Welles Wilder ADX."""
    up = high.diff()
    down = -low.diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = _true_range(high, low, close)
    atr = _wilder(tr, n)
    plus_di = 100.0 * _wilder(pd.Series(plus_dm, index=high.index), n) / atr
    minus_di = 100.0 * _wilder(pd.Series(minus_dm, index=high.index), n) / atr
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return _wilder(dx, n)


def _cci(high, low, close, n: int = 20) -> pd.Series:
    tp = (high + low + close) / 3.0
    sma_tp = tp.rolling(n, min_periods=n).mean()
    mad = tp.rolling(n, min_periods=n).apply(
        lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    return (tp - sma_tp) / (0.015 * mad.replace(0, np.nan))


def calculate_supertrend(df: pd.DataFrame,
                         period: int = SUPERTREND_PERIOD,
                         multiplier: float = SUPERTREND_MULT):
    """SuperTrend per common implementation. Returns (line, direction) Series.
    direction: +1 bullish, -1 bearish; first valid bar starts at +1."""
    atr = _atr(df["high"], df["low"], df["close"], period)
    hl2 = (df["high"] + df["low"]) / 2.0
    upper = hl2 + multiplier * atr
    lower = hl2 - multiplier * atr

    n = len(df)
    line = np.full(n, np.nan)
    direction = np.full(n, 1, dtype=int)
    final_upper = np.array(upper.to_numpy(), copy=True)
    final_lower = np.array(lower.to_numpy(), copy=True)

    close = np.array(df["close"].to_numpy(), copy=True)
    for i in range(1, n):
        # Tighten bands
        if not np.isnan(final_upper[i - 1]):
            if final_upper[i] > final_upper[i - 1] and close[i - 1] <= final_upper[i - 1]:
                final_upper[i] = final_upper[i - 1]
        if not np.isnan(final_lower[i - 1]):
            if final_lower[i] < final_lower[i - 1] and close[i - 1] >= final_lower[i - 1]:
                final_lower[i] = final_lower[i - 1]

        # Direction & line
        if close[i] > final_upper[i - 1]:
            direction[i] = 1
        elif close[i] < final_lower[i - 1]:
            direction[i] = -1
        else:
            direction[i] = direction[i - 1]
        line[i] = final_lower[i] if direction[i] == 1 else final_upper[i]

    return pd.Series(line, index=df.index), pd.Series(direction, index=df.index)


# =============================================================================
# 8-layer scoring
# =============================================================================
def score_layers(df: pd.DataFrame):
    """Score each candle across 8 layers.
    Returns (long_scores, short_scores, atr) all aligned to df.index.

    Layer agreement is bool→int. Layers 5/6 (volume + ADX) are
    direction-agnostic (per spec) — they vote for both directions when their
    condition fires. Layer 7 (candle) and the others are directional.
    """
    close, high, low, vol, op = (df["close"], df["high"], df["low"],
                                   df["volume"], df["open"])

    ema_fast = _ema(close, EMA_FAST)
    ema_slow = _ema(close, EMA_SLOW)
    rsi = _rsi(close, RSI_PERIOD)
    _, _, macd_hist = _macd(close, MACD_FAST, MACD_SLOW, MACD_SIGNAL)
    vol_sma = _sma(vol, VOLUME_SMA)
    adx = _adx(high, low, close, ADX_PERIOD)
    cci = _cci(high, low, close, CCI_PERIOD)
    _, st_dir = calculate_supertrend(df)
    atr = _atr(high, low, close, ATR_PERIOD)

    long_s = pd.Series(0, index=df.index)
    short_s = pd.Series(0, index=df.index)

    # 1. EMA Alignment
    long_s += (ema_fast > ema_slow).astype(int)
    short_s += (ema_fast < ema_slow).astype(int)

    # 2. RSI Power Zone (long: 40..65 ; short: mirrored 35..60)
    long_s += ((rsi >= RSI_LOW) & (rsi <= RSI_HIGH)).astype(int)
    short_s += ((rsi >= (100 - RSI_HIGH)) & (rsi <= (100 - RSI_LOW))).astype(int)

    # 3. MACD Histogram
    long_s += (macd_hist > 0).astype(int)
    short_s += (macd_hist < 0).astype(int)

    # 4. SuperTrend
    long_s += (st_dir == 1).astype(int)
    short_s += (st_dir == -1).astype(int)

    # 5. Volume Surge — direction-agnostic, both sides credit it
    vol_surge = vol > (vol_sma * VOLUME_MULT)
    long_s += vol_surge.astype(int)
    short_s += vol_surge.astype(int)

    # 6. ADX Strength — direction-agnostic
    adx_ok = (adx > ADX_MIN)
    long_s += adx_ok.astype(int)
    short_s += adx_ok.astype(int)

    # 7. Bullish/Bearish Candle (close in upper 60% / lower 40%)
    candle_range = (high - low).replace(0, np.nan)
    pos = (close - low) / candle_range
    bullish = (close > op) & (pos >= 0.6)
    bearish = (close < op) & (pos <= 0.4)
    long_s += bullish.fillna(False).astype(int)
    short_s += bearish.fillna(False).astype(int)

    # 8. CCI direction
    long_s += (cci > 0).astype(int)
    short_s += (cci < 0).astype(int)

    return long_s, short_s, atr


def generate_signals(df: pd.DataFrame, min_layers: int = MIN_LAYERS) -> pd.DataFrame:
    """Return df annotated with long_score, short_score, atr, signal, sl, tp.
    A bar with both long_score >= min_layers AND short_score >= min_layers is
    rare (the direction-agnostic layers cap shared overlap at 3) but if it
    happens we let LONG win — short_mask is applied second only when long_mask
    is False, mirroring the spec.
    """
    long_s, short_s, atr = score_layers(df)
    out = df.copy()
    out["long_score"] = long_s
    out["short_score"] = short_s
    out["atr"] = atr
    out["signal"] = 0
    out["sl"] = np.nan
    out["tp"] = np.nan

    long_mask = long_s >= min_layers
    short_mask = (~long_mask) & (short_s >= min_layers)

    out.loc[long_mask, "signal"] = 1
    out.loc[long_mask, "sl"] = out.loc[long_mask, "close"] - atr[long_mask] * ATR_SL_MULT
    out.loc[long_mask, "tp"] = out.loc[long_mask, "close"] + atr[long_mask] * ATR_TP_MULT

    out.loc[short_mask, "signal"] = -1
    out.loc[short_mask, "sl"] = out.loc[short_mask, "close"] + atr[short_mask] * ATR_SL_MULT
    out.loc[short_mask, "tp"] = out.loc[short_mask, "close"] - atr[short_mask] * ATR_TP_MULT

    return out
