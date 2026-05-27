"""
SMT Divergence Detection (Confluence 6)
==========================================
Smart Money Technique — compares QQQ swing points against SPY
to identify divergences that signal institutional activity.
"""

import time
from strategies.templates.base_strategy import CandleData
from strategies.augxmented.confluences.bos import find_swing_points

# Module-level cache for SPY data
_spy_cache: dict = {'data': None, 'timestamp': 0.0}
SPY_CACHE_TTL = 300  # 5 minutes


def fetch_spy_candles(api, timeframe: str = '5Min', limit: int = 100) -> list[CandleData]:
    """
    Fetch SPY candles via Alpaca API with 5-minute caching.

    Args:
        api: Alpaca REST API client instance.
        timeframe: Bar timeframe (default '5Min').
        limit: Number of bars to fetch.

    Returns:
        List of CandleData objects for SPY.
    """
    now = time.time()
    if _spy_cache['data'] is not None and (now - _spy_cache['timestamp']) < SPY_CACHE_TTL:
        return _spy_cache['data']

    try:
        bars = api.get_bars('SPY', timeframe, limit=limit).df
        candles = []
        for ts, row in bars.iterrows():
            candles.append(CandleData(
                timestamp_ms=int(ts.timestamp() * 1000),
                open=float(row['open']),
                high=float(row['high']),
                low=float(row['low']),
                close=float(row['close']),
                volume=float(row['volume']),
            ))
        _spy_cache['data'] = candles
        _spy_cache['timestamp'] = now
        return candles
    except Exception:
        # Return cached data if available, empty list otherwise
        return _spy_cache['data'] or []


def detect_smt_divergence(qqq_candles: list[CandleData],
                          spy_candles: list[CandleData],
                          lookback: int = 20) -> dict | None:
    """
    Detect SMT divergence between QQQ and SPY.

    Bullish SMT: QQQ makes a lower low but SPY does NOT (QQQ is weak, reversal up).
    Bearish SMT: QQQ makes a higher high but SPY does NOT (QQQ is strong, reversal down).

    Args:
        qqq_candles: QQQ candle history.
        spy_candles: SPY candle history.
        lookback: Number of bars to compare swings over.

    Returns:
        Dict {direction, qqq_swing, spy_swing} or None.
    """
    min_len = min(len(qqq_candles), len(spy_candles))
    if min_len < lookback + 10:
        return None

    # Use the last `lookback` candles for comparison
    qqq_recent = qqq_candles[-lookback:]
    spy_recent = spy_candles[-lookback:]

    qqq_highs = [c.high for c in qqq_recent]
    qqq_lows = [c.low for c in qqq_recent]
    spy_highs = [c.high for c in spy_recent]
    spy_lows = [c.low for c in spy_recent]

    # Find swing points in both instruments
    sw = min(3, lookback // 4)  # smaller lookback for swing detection within window
    if sw < 1:
        sw = 1

    qqq_swings = find_swing_points(qqq_highs, qqq_lows, lookback=sw)
    spy_swings = find_swing_points(spy_highs, spy_lows, lookback=sw)

    if len(qqq_swings) < 2 or len(spy_swings) < 2:
        return None

    # Get the two most recent swing lows and highs for each
    qqq_swing_lows = [s for s in qqq_swings if s['type'] == 'low']
    qqq_swing_highs = [s for s in qqq_swings if s['type'] == 'high']
    spy_swing_lows = [s for s in spy_swings if s['type'] == 'low']
    spy_swing_highs = [s for s in spy_swings if s['type'] == 'high']

    # Bullish SMT: QQQ lower low, SPY higher low (or equal)
    if len(qqq_swing_lows) >= 2 and len(spy_swing_lows) >= 2:
        qqq_ll = qqq_swing_lows[-1]['price'] < qqq_swing_lows[-2]['price']
        spy_ll = spy_swing_lows[-1]['price'] < spy_swing_lows[-2]['price']
        if qqq_ll and not spy_ll:
            return {
                'direction': 1,
                'qqq_swing': qqq_swing_lows[-1]['price'],
                'spy_swing': spy_swing_lows[-1]['price'],
            }

    # Bearish SMT: QQQ higher high, SPY lower high (or equal)
    if len(qqq_swing_highs) >= 2 and len(spy_swing_highs) >= 2:
        qqq_hh = qqq_swing_highs[-1]['price'] > qqq_swing_highs[-2]['price']
        spy_hh = spy_swing_highs[-1]['price'] > spy_swing_highs[-2]['price']
        if qqq_hh and not spy_hh:
            return {
                'direction': -1,
                'qqq_swing': qqq_swing_highs[-1]['price'],
                'spy_swing': spy_swing_highs[-1]['price'],
            }

    return None


def score_smt(qqq_candles: list[CandleData],
              spy_candles: list[CandleData],
              lookback: int = 20) -> dict:
    """
    Score SMT divergence confluence.

    Args:
        qqq_candles: QQQ candle history.
        spy_candles: SPY candle history.
        lookback: Lookback bars for divergence detection.

    Returns:
        Dict with 'smt_divergence' (0|1).
    """
    smt = detect_smt_divergence(qqq_candles, spy_candles, lookback=lookback)
    if smt is not None:
        return {'smt_divergence': 1}
    return {'smt_divergence': 0}
