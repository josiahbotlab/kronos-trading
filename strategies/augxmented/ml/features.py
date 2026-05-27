"""
Feature Extraction for ML Regime Filter
==========================================
Extracts a feature vector from the candle state at signal time.

Features (14 total):
  1. atr_ratio          — ATR(14) / ATR(50), measures volatility expansion
  2. vwap_position      — (price - VWAP) / ATR, signed distance from VWAP
  3. swing_hh           — 1 if higher high detected on 5m
  4. swing_hl           — 1 if higher low detected
  5. swing_lh           — 1 if lower high detected
  6. swing_ll           — 1 if lower low detected
  7. volume_ratio       — current volume / 20-bar avg volume
  8. session_hour       — hour of day (ET), normalized 0-1
  9. htf_1h_bullish     — 1 if 1h structure is bullish
  10. htf_1h_bearish    — 1 if 1h structure is bearish
  11. htf_4h_bullish    — 1 if 4h structure is bullish
  12. htf_4h_bearish    — 1 if 4h structure is bearish
  13. confluence_score   — raw weighted score (normalized by max possible 20)
  14. premium_discount   — position in recent range (0=swing low, 1=swing high)
"""

import numpy as np
from datetime import datetime, timezone, timedelta
from strategies.templates.base_strategy import CandleData

ET_OFFSET = timedelta(hours=-5)

FEATURE_NAMES = [
    'atr_ratio', 'vwap_position',
    'swing_hh', 'swing_hl', 'swing_lh', 'swing_ll',
    'volume_ratio', 'session_hour',
    'htf_1h_bullish', 'htf_1h_bearish',
    'htf_4h_bullish', 'htf_4h_bearish',
    'confluence_score', 'premium_discount',
]


def extract_features(
    candles: list[CandleData],
    direction: int,
    current_atr: float,
    breakdown: dict,
    total_score: float,
    htf_1h_trend: str,
    htf_4h_trend: str,
    timestamp_ms: int,
) -> np.ndarray:
    """
    Extract a feature vector from the current market state at signal time.

    Args:
        candles: Full candle history (5m).
        direction: Trade direction (1=long, -1=short).
        current_atr: ATR(14) at current bar.
        breakdown: Confluence score breakdown dict.
        total_score: Total weighted confluence score.
        htf_1h_trend: 1h structure trend string.
        htf_4h_trend: 4h structure trend string.
        timestamp_ms: Current candle timestamp.

    Returns:
        numpy array of shape (14,) with feature values.
    """
    features = np.zeros(len(FEATURE_NAMES))

    # 1. ATR ratio — volatility expansion/contraction
    if len(candles) >= 50:
        closes = np.array([c.close for c in candles[-51:]])
        # Simple ATR(50) approximation using true range
        highs = np.array([c.high for c in candles[-51:]])
        lows = np.array([c.low for c in candles[-51:]])
        tr = np.maximum(highs[1:] - lows[1:],
                        np.maximum(np.abs(highs[1:] - closes[:-1]),
                                   np.abs(lows[1:] - closes[:-1])))
        atr_50 = np.mean(tr)
        features[0] = current_atr / atr_50 if atr_50 > 0 else 1.0
    else:
        features[0] = 1.0

    # 2. VWAP position — distance from session VWAP in ATR units
    if len(candles) >= 20 and current_atr > 0:
        recent = candles[-78:]  # ~6.5 hours of 5m bars (full session)
        tp_vol = sum(
            ((c.high + c.low + c.close) / 3) * c.volume for c in recent
        )
        total_vol = sum(c.volume for c in recent)
        if total_vol > 0:
            vwap = tp_vol / total_vol
            features[1] = (candles[-1].close - vwap) / current_atr
        else:
            features[1] = 0.0

    # 3-6. Swing structure (from the confluence breakdown or recomputed)
    from strategies.augxmented.confluences.structure import detect_structure
    structure = detect_structure(candles)
    features[2] = 1.0 if structure['hh'] else 0.0
    features[3] = 1.0 if structure['hl'] else 0.0
    features[4] = 1.0 if structure['lh'] else 0.0
    features[5] = 1.0 if structure['ll'] else 0.0

    # 7. Volume ratio
    if len(candles) >= 21:
        volumes = [c.volume for c in candles[-21:]]
        avg_vol = np.mean(volumes[:-1])
        features[6] = volumes[-1] / avg_vol if avg_vol > 0 else 1.0
    else:
        features[6] = 1.0

    # 8. Session hour (ET), normalized to 0-1
    dt_utc = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
    dt_et = dt_utc + ET_OFFSET
    features[7] = (dt_et.hour + dt_et.minute / 60.0) / 24.0

    # 9-12. HTF trend flags
    features[8] = 1.0 if htf_1h_trend == 'bullish' else 0.0
    features[9] = 1.0 if htf_1h_trend == 'bearish' else 0.0
    features[10] = 1.0 if htf_4h_trend == 'bullish' else 0.0
    features[11] = 1.0 if htf_4h_trend == 'bearish' else 0.0

    # 13. Confluence score (normalized by max possible = 20)
    features[12] = total_score / 20.0

    # 14. Premium/discount position in recent range
    if len(candles) >= 50:
        recent = candles[-50:]
        swing_high = max(c.high for c in recent)
        swing_low = min(c.low for c in recent)
        rng = swing_high - swing_low
        if rng > 0:
            features[13] = (candles[-1].close - swing_low) / rng
        else:
            features[13] = 0.5
    else:
        features[13] = 0.5

    return features
