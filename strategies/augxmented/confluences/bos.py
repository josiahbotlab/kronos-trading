"""
Break of Structure Detection (Confluence 5 — ENTRY TRIGGER)
==============================================================
Identifies swing points and detects structural breaks (BOS).
BOS is the mandatory entry trigger — no trade fires without it.
"""

from strategies.templates.base_strategy import CandleData


def find_swing_points(highs: list[float], lows: list[float],
                      lookback: int = 5) -> list[dict]:
    """
    Identify swing highs and swing lows using a lookback window.

    A swing high is the highest point with `lookback` bars on each side
    all having lower highs. Vice versa for swing lows.

    Args:
        highs: List of high prices.
        lows: List of low prices.
        lookback: Number of bars on each side to confirm swing.

    Returns:
        List of swing point dicts: {type, price, index}, sorted by index.
    """
    swings = []
    n = len(highs)
    if n < lookback * 2 + 1:
        return swings

    for i in range(lookback, n - lookback):
        # Swing high: highest high in the window
        is_swing_high = True
        for j in range(i - lookback, i + lookback + 1):
            if j == i:
                continue
            if highs[j] >= highs[i]:
                is_swing_high = False
                break

        if is_swing_high:
            swings.append({'type': 'high', 'price': highs[i], 'index': i})

        # Swing low: lowest low in the window
        is_swing_low = True
        for j in range(i - lookback, i + lookback + 1):
            if j == i:
                continue
            if lows[j] <= lows[i]:
                is_swing_low = False
                break

        if is_swing_low:
            swings.append({'type': 'low', 'price': lows[i], 'index': i})

    swings.sort(key=lambda s: s['index'])
    return swings


def detect_bos(candles: list[CandleData], swing_lookback: int = 20) -> dict | None:
    """
    Detect Break of Structure on the most recent candle.

    Bullish BOS: current close breaks above the most recent swing high.
    Bearish BOS: current close breaks below the most recent swing low.

    Args:
        candles: Candle history (needs at least swing_lookback * 2 + 1 bars).
        swing_lookback: Lookback for swing point detection.

    Returns:
        BOS dict {direction, break_price, swing_price, candle_index} or None.
    """
    if len(candles) < swing_lookback * 2 + 2:
        return None

    highs = [c.high for c in candles]
    lows = [c.low for c in candles]

    # Find swing points up to the second-to-last candle
    # (current candle is the one potentially breaking structure)
    swings = find_swing_points(highs[:-1], lows[:-1], lookback=min(swing_lookback, 5))
    if not swings:
        return None

    current = candles[-1]

    # Find the most recent swing high and swing low
    recent_high = None
    recent_low = None
    for s in reversed(swings):
        if s['type'] == 'high' and recent_high is None:
            recent_high = s
        if s['type'] == 'low' and recent_low is None:
            recent_low = s
        if recent_high and recent_low:
            break

    # Bullish BOS: close above most recent swing high
    if recent_high and current.close > recent_high['price']:
        return {
            'direction': 1,
            'break_price': current.close,
            'swing_price': recent_high['price'],
            'candle_index': len(candles) - 1,
        }

    # Bearish BOS: close below most recent swing low
    if recent_low and current.close < recent_low['price']:
        return {
            'direction': -1,
            'break_price': current.close,
            'swing_price': recent_low['price'],
            'candle_index': len(candles) - 1,
        }

    return None


def score_bos(candles: list[CandleData], swing_lookback: int = 20) -> tuple[dict, int]:
    """
    Score BOS confluence and return the detected direction.

    Args:
        candles: Candle history.
        swing_lookback: Lookback for swing detection.

    Returns:
        Tuple of (scores dict {'bos_trigger': 0|1}, direction int 1|-1|0).
    """
    bos = detect_bos(candles, swing_lookback=swing_lookback)
    if bos is not None:
        return {'bos_trigger': 1}, bos['direction']
    return {'bos_trigger': 0}, 0
