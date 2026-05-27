"""
Order Block Detection (Confluences 3-4)
==========================================
Detects Order Blocks (last opposing candle before impulsive move)
and Breaker Blocks (broken OBs that flip support/resistance).
"""

from strategies.templates.base_strategy import CandleData


def detect_order_blocks(candles: list[CandleData], move_threshold_atr: float = 1.5,
                        atr: float = 0.0) -> list[dict]:
    """
    Detect Order Blocks in a candle series.

    Bullish OB: last bearish candle before an impulsive move up (> threshold).
    Bearish OB: last bullish candle before an impulsive move down (> threshold).

    Args:
        candles: List of CandleData (chronological).
        move_threshold_atr: Minimum move size as ATR multiplier.
        atr: Current ATR value. If 0, uses a simple estimate.

    Returns:
        List of OB dicts with type, high, low, midpoint, candle_index, broken.
    """
    obs = []
    if len(candles) < 5:
        return obs

    # Estimate ATR if not provided
    if atr <= 0:
        atr = _estimate_atr(candles)
    if atr <= 0:
        return obs

    threshold = atr * move_threshold_atr

    for i in range(1, len(candles) - 2):
        c = candles[i]
        is_bearish = c.close < c.open
        is_bullish = c.close > c.open

        # Look at the move in the next 1-3 candles after this candle
        move_up = max(candles[j].high for j in range(i + 1, min(i + 4, len(candles)))) - c.close
        move_down = c.close - min(candles[j].low for j in range(i + 1, min(i + 4, len(candles))))

        # Bullish OB: bearish candle followed by impulsive move up
        if is_bearish and move_up >= threshold:
            obs.append({
                'type': 'bullish',
                'high': c.high,
                'low': c.low,
                'midpoint': (c.high + c.low) / 2,
                'candle_index': i,
                'broken': False,
            })

        # Bearish OB: bullish candle followed by impulsive move down
        if is_bullish and move_down >= threshold:
            obs.append({
                'type': 'bearish',
                'high': c.high,
                'low': c.low,
                'midpoint': (c.high + c.low) / 2,
                'candle_index': i,
                'broken': False,
            })

    # Mark broken OBs (price traded through the OB zone)
    for ob in obs:
        idx = ob['candle_index']
        for j in range(idx + 1, len(candles)):
            if ob['type'] == 'bullish' and candles[j].close < ob['low']:
                ob['broken'] = True
                break
            elif ob['type'] == 'bearish' and candles[j].close > ob['high']:
                ob['broken'] = True
                break

    return obs


def detect_breaker_blocks(candles: list[CandleData], order_blocks: list[dict]) -> list[dict]:
    """
    Detect Breaker Blocks — OBs that were broken and price returned to.

    A breaker block is an order block that failed (price broke through it),
    then price came back to retest the zone from the other side, flipping
    the support/resistance role.

    Args:
        candles: Full candle series.
        order_blocks: OB list from detect_order_blocks().

    Returns:
        List of breaker block dicts.
    """
    breakers = []

    for ob in order_blocks:
        if not ob['broken']:
            continue

        idx = ob['candle_index']
        # Find where it broke
        break_idx = None
        for j in range(idx + 1, len(candles)):
            if ob['type'] == 'bullish' and candles[j].close < ob['low']:
                break_idx = j
                break
            elif ob['type'] == 'bearish' and candles[j].close > ob['high']:
                break_idx = j
                break

        if break_idx is None:
            continue

        # Check if price returned to the zone after breaking
        for j in range(break_idx + 1, min(break_idx + 30, len(candles))):
            c = candles[j]
            if ob['type'] == 'bullish':
                # Broken bullish OB becomes bearish breaker — price retests from below
                if c.high >= ob['low'] and c.high <= ob['high']:
                    breakers.append({
                        'type': 'bearish',  # flipped role
                        'high': ob['high'],
                        'low': ob['low'],
                        'midpoint': ob['midpoint'],
                        'candle_index': ob['candle_index'],
                        'break_index': break_idx,
                        'retest_index': j,
                    })
                    break
            elif ob['type'] == 'bearish':
                # Broken bearish OB becomes bullish breaker — price retests from above
                if c.low <= ob['high'] and c.low >= ob['low']:
                    breakers.append({
                        'type': 'bullish',  # flipped role
                        'high': ob['high'],
                        'low': ob['low'],
                        'midpoint': ob['midpoint'],
                        'candle_index': ob['candle_index'],
                        'break_index': break_idx,
                        'retest_index': j,
                    })
                    break

    return breakers


def score_ob(candles: list[CandleData], direction: int, atr: float) -> dict:
    """
    Score Order Block confluences for a given trade direction.

    Args:
        candles: Candle history.
        direction: 1 for long, -1 for short.
        atr: Current ATR value.

    Returns:
        Dict with 'order_block' (0|1) and 'breaker_block' (0|1).
    """
    scores = {'order_block': 0, 'breaker_block': 0}
    if len(candles) < 5 or atr <= 0:
        return scores

    obs = detect_order_blocks(candles, atr=atr)
    current_price = candles[-1].close

    # Check for aligned, unbroken OBs near current price
    for ob in obs:
        if ob['broken']:
            continue
        if ob['candle_index'] < len(candles) - 50:
            continue  # too old

        if direction == 1 and ob['type'] == 'bullish':
            # Bullish OB below price = demand zone for long
            if ob['low'] <= current_price <= ob['high'] * 1.02:
                scores['order_block'] = 1
                break
        elif direction == -1 and ob['type'] == 'bearish':
            # Bearish OB above price = supply zone for short
            if ob['high'] >= current_price >= ob['low'] * 0.98:
                scores['order_block'] = 1
                break

    # Check breaker blocks
    breakers = detect_breaker_blocks(candles, obs)
    for bb in breakers:
        if direction == 1 and bb['type'] == 'bullish':
            if bb['low'] <= current_price <= bb['high'] * 1.02:
                scores['breaker_block'] = 1
                break
        elif direction == -1 and bb['type'] == 'bearish':
            if bb['high'] >= current_price >= bb['low'] * 0.98:
                scores['breaker_block'] = 1
                break

    return scores


def _estimate_atr(candles: list[CandleData], period: int = 14) -> float:
    """Simple ATR estimate from candle data."""
    if len(candles) < period + 1:
        return 0.0
    trs = []
    for i in range(1, min(period + 1, len(candles))):
        c = candles[-i]
        prev = candles[-i - 1]
        tr = max(c.high - c.low, abs(c.high - prev.close), abs(c.low - prev.close))
        trs.append(tr)
    return sum(trs) / len(trs) if trs else 0.0
