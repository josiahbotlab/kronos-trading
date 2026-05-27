"""
Market Structure + Premium/Discount + Volume/Momentum (Confluences 7-12)
==========================================================================
Higher-timeframe structure alignment, price zone analysis, and momentum filters.
"""

import numpy as np
from strategies.templates.base_strategy import CandleData
from strategies.augxmented.confluences.bos import find_swing_points
from strategies.augxmented.config import STRUCTURE_SWING_LOOKBACK, VOL_SPIKE_MULT


def detect_structure(candles: list[CandleData],
                     lookback: int = STRUCTURE_SWING_LOOKBACK) -> dict:
    """
    Detect market structure: higher highs/lows (bullish) or lower highs/lows (bearish).

    Args:
        candles: Candle history.
        lookback: Swing detection lookback.

    Returns:
        Dict with trend ('bullish'|'bearish'|'neutral') and HH/HL/LH/LL booleans.
    """
    result = {'trend': 'neutral', 'hh': False, 'hl': False, 'lh': False, 'll': False}

    if len(candles) < lookback * 2 + 5:
        return result

    highs = [c.high for c in candles]
    lows = [c.low for c in candles]
    sw = min(lookback, 3)
    swings = find_swing_points(highs, lows, lookback=sw)

    swing_highs = [s for s in swings if s['type'] == 'high']
    swing_lows = [s for s in swings if s['type'] == 'low']

    if len(swing_highs) >= 2:
        result['hh'] = swing_highs[-1]['price'] > swing_highs[-2]['price']
        result['lh'] = swing_highs[-1]['price'] < swing_highs[-2]['price']

    if len(swing_lows) >= 2:
        result['hl'] = swing_lows[-1]['price'] > swing_lows[-2]['price']
        result['ll'] = swing_lows[-1]['price'] < swing_lows[-2]['price']

    # Determine trend
    if result['hh'] and result['hl']:
        result['trend'] = 'bullish'
    elif result['lh'] and result['ll']:
        result['trend'] = 'bearish'

    return result


def score_htf_structure(candles_by_tf: dict[str, list[CandleData]],
                        direction: int) -> dict:
    """
    Score higher-timeframe structure alignment.

    Args:
        candles_by_tf: Dict mapping timeframe strings to candle lists.
                       Expected keys: '1h', '4h'.
        direction: Trade direction (1=long, -1=short).

    Returns:
        Dict with 'htf_structure_1h' (0|1) and 'htf_structure_4h' (0|1).
    """
    scores = {'htf_structure_1h': 0, 'htf_structure_4h': 0}

    expected_trend = 'bullish' if direction == 1 else 'bearish'

    for tf, key in [('1h', 'htf_structure_1h'), ('4h', 'htf_structure_4h')]:
        candles = candles_by_tf.get(tf, [])
        if len(candles) >= 20:
            structure = detect_structure(candles)
            if structure['trend'] == expected_trend:
                scores[key] = 1

    return scores


def score_premium_discount(candles: list[CandleData], direction: int) -> dict:
    """
    Score whether price is in the correct zone for the trade direction.

    Longs want price in discount (lower 50% of recent range).
    Shorts want price in premium (upper 50% of recent range).

    Args:
        candles: Candle history (uses last 50 bars for range).
        direction: 1=long, -1=short.

    Returns:
        Dict with 'premium_discount' (0|1).
    """
    scores = {'premium_discount': 0}

    lookback = min(50, len(candles))
    if lookback < 10:
        return scores

    recent = candles[-lookback:]
    swing_high = max(c.high for c in recent)
    swing_low = min(c.low for c in recent)
    swing_range = swing_high - swing_low

    if swing_range <= 0:
        return scores

    current_price = candles[-1].close
    midpoint = swing_low + swing_range / 2

    if direction == 1 and current_price <= midpoint:
        scores['premium_discount'] = 1  # in discount zone for long
    elif direction == -1 and current_price >= midpoint:
        scores['premium_discount'] = 1  # in premium zone for short

    return scores


def score_volume_momentum(candles: list[CandleData], direction: int) -> dict:
    """
    Score volume spike and RSI divergence confluences.

    Args:
        candles: Candle history (needs 20+ bars).
        direction: 1=long, -1=short.

    Returns:
        Dict with 'volume_spike' (0|1) and 'rsi_divergence' (0|1).
    """
    scores = {'volume_spike': 0, 'rsi_divergence': 0}

    if len(candles) < 21:
        return scores

    # Volume spike: current volume > VOL_SPIKE_MULT * 20-bar average
    volumes = np.array([c.volume for c in candles[-21:]])
    avg_vol = np.mean(volumes[:-1])
    if avg_vol > 0 and volumes[-1] > avg_vol * VOL_SPIKE_MULT:
        scores['volume_spike'] = 1

    # RSI divergence
    if len(candles) >= 30:
        scores['rsi_divergence'] = _check_rsi_divergence(candles, direction)

    return scores


def _check_rsi_divergence(candles: list[CandleData], direction: int) -> int:
    """
    Check for RSI divergence with price.

    Bullish: price makes lower low but RSI makes higher low.
    Bearish: price makes higher high but RSI makes lower high.
    """
    closes = np.array([c.close for c in candles[-30:]])
    rsi_values = _compute_rsi_series(closes, period=14)

    if len(rsi_values) < 4:
        return 0

    # Split RSI and matching price tail into two halves for comparison
    rsi_half = len(rsi_values) // 2
    if rsi_half < 2:
        return 0

    # Align price array to RSI (RSI starts after period warmup)
    price_tail = closes[-(len(rsi_values)):]

    if direction == 1:
        # Bullish RSI divergence: lower price low, higher RSI low
        price_low_1 = np.min(price_tail[:rsi_half])
        price_low_2 = np.min(price_tail[rsi_half:])
        rsi_low_1 = np.min(rsi_values[:rsi_half])
        rsi_low_2 = np.min(rsi_values[rsi_half:])
        if price_low_2 < price_low_1 and rsi_low_2 > rsi_low_1:
            return 1
    elif direction == -1:
        # Bearish RSI divergence: higher price high, lower RSI high
        price_high_1 = np.max(price_tail[:rsi_half])
        price_high_2 = np.max(price_tail[rsi_half:])
        rsi_high_1 = np.max(rsi_values[:rsi_half])
        rsi_high_2 = np.max(rsi_values[rsi_half:])
        if price_high_2 > price_high_1 and rsi_high_2 < rsi_high_1:
            return 1

    return 0


def _compute_rsi_series(closes: np.ndarray, period: int = 14) -> np.ndarray:
    """Compute RSI for each bar in the series."""
    if len(closes) < period + 1:
        return np.array([])

    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    rsi_values = []
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi_values.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi_values.append(100.0 - 100.0 / (1.0 + rs))

    return np.array(rsi_values)
