"""
Fair Value Gap Detection (Confluences 1-2)
=============================================
Detects bullish/bearish FVGs and inverse FVGs (price retests gap zone).
"""

from strategies.templates.base_strategy import CandleData


def detect_fvgs(candles: list[CandleData], min_gap_pct: float = 0.0) -> list[dict]:
    """
    Detect Fair Value Gaps in a candle series.

    Bullish FVG: candle[i-2].high < candle[i].low (gap up through middle candle)
    Bearish FVG: candle[i-2].low > candle[i].high (gap down through middle candle)

    Args:
        candles: List of CandleData (chronological).
        min_gap_pct: Minimum gap size as fraction of price (0.0 = any gap).

    Returns:
        List of FVG dicts with type, top, bottom, midpoint, candle_index, filled.
    """
    fvgs = []
    if len(candles) < 3:
        return fvgs

    for i in range(2, len(candles)):
        prev2 = candles[i - 2]
        curr = candles[i]
        mid_price = candles[i - 1].close

        # Bullish FVG: gap between candle[i-2] high and candle[i] low
        if prev2.high < curr.low:
            gap = curr.low - prev2.high
            if min_gap_pct <= 0 or (mid_price > 0 and gap / mid_price >= min_gap_pct):
                fvgs.append({
                    'type': 'bullish',
                    'top': curr.low,
                    'bottom': prev2.high,
                    'midpoint': (curr.low + prev2.high) / 2,
                    'candle_index': i,
                    'filled': False,
                })

        # Bearish FVG: gap between candle[i-2] low and candle[i] high
        if prev2.low > curr.high:
            gap = prev2.low - curr.high
            if min_gap_pct <= 0 or (mid_price > 0 and gap / mid_price >= min_gap_pct):
                fvgs.append({
                    'type': 'bearish',
                    'top': prev2.low,
                    'bottom': curr.high,
                    'midpoint': (prev2.low + curr.high) / 2,
                    'candle_index': i,
                    'filled': False,
                })

    # Mark filled FVGs (price returned to fill the gap)
    for fvg in fvgs:
        idx = fvg['candle_index']
        for j in range(idx + 1, len(candles)):
            if fvg['type'] == 'bullish' and candles[j].low <= fvg['bottom']:
                fvg['filled'] = True
                break
            elif fvg['type'] == 'bearish' and candles[j].high >= fvg['top']:
                fvg['filled'] = True
                break

    return fvgs


def check_inverse_fvg(candles: list[CandleData], fvgs: list[dict]) -> list[dict]:
    """
    Identify inverse FVGs — FVGs where price returned to the zone and reacted.

    An FVG becomes "inverse" when price touches the zone and then reverses,
    turning the gap into a support/resistance zone.

    Args:
        candles: Full candle series.
        fvgs: FVG list from detect_fvgs().

    Returns:
        List of active inverse FVG dicts.
    """
    inverse = []
    if not fvgs or len(candles) < 5:
        return inverse

    for fvg in fvgs:
        idx = fvg['candle_index']
        touched = False
        reaction = False

        for j in range(idx + 1, min(idx + 30, len(candles))):
            c = candles[j]

            if fvg['type'] == 'bullish':
                # Price dipped into the bullish FVG zone
                if c.low <= fvg['top'] and c.low >= fvg['bottom']:
                    touched = True
                # After touch, price bounced back up
                if touched and j + 1 < len(candles):
                    if candles[j + 1].close > c.close:
                        reaction = True
                        break

            elif fvg['type'] == 'bearish':
                # Price rallied into the bearish FVG zone
                if c.high >= fvg['bottom'] and c.high <= fvg['top']:
                    touched = True
                # After touch, price dropped back down
                if touched and j + 1 < len(candles):
                    if candles[j + 1].close < c.close:
                        reaction = True
                        break

        if touched and reaction:
            inverse.append({**fvg, 'inverse': True})

    return inverse


def score_fvg(candles: list[CandleData], direction: int, atr: float) -> dict:
    """
    Score FVG confluences for a given trade direction.

    Args:
        candles: Candle history.
        direction: 1 for long, -1 for short.
        atr: Current ATR value for gap filtering.

    Returns:
        Dict with 'fvg_present' (0|1) and 'inverse_fvg' (0|1).
    """
    scores = {'fvg_present': 0, 'inverse_fvg': 0}
    if len(candles) < 3 or atr <= 0:
        return scores

    min_gap = atr * 0.3  # FVG_MIN_GAP_ATR_MULT
    mid_price = candles[-1].close if candles[-1].close > 0 else 1.0
    min_gap_pct = min_gap / mid_price

    fvgs = detect_fvgs(candles, min_gap_pct=min_gap_pct)

    # Check for aligned, unfilled FVGs near current price
    current_price = candles[-1].close
    recent_fvgs = [f for f in fvgs if not f['filled'] and f['candle_index'] >= len(candles) - 30]

    for fvg in recent_fvgs:
        if direction == 1 and fvg['type'] == 'bullish':
            # Bullish FVG below price = support for long
            if fvg['top'] <= current_price:
                scores['fvg_present'] = 1
                break
        elif direction == -1 and fvg['type'] == 'bearish':
            # Bearish FVG above price = resistance for short
            if fvg['bottom'] >= current_price:
                scores['fvg_present'] = 1
                break

    # Check for inverse FVGs
    inverse = check_inverse_fvg(candles, recent_fvgs)
    for inv in inverse:
        if direction == 1 and inv['type'] == 'bullish':
            scores['inverse_fvg'] = 1
            break
        elif direction == -1 and inv['type'] == 'bearish':
            scores['inverse_fvg'] = 1
            break

    return scores
