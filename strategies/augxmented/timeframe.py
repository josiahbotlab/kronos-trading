"""
Multi-Timeframe Candle Aggregation
====================================
Builds higher-TF candles (15m, 30m, 1h, 4h) from 5m candle history.
"""

from strategies.templates.base_strategy import CandleData

# Number of 5m candles per target timeframe
TF_MULTIPLIERS = {
    '5m': 1,
    '15m': 3,
    '30m': 6,
    '1h': 12,
    '4h': 48,
}


def aggregate_candles(candles_5m: list[CandleData], target_tf: str) -> list[CandleData]:
    """
    Aggregate 5m candles into a higher timeframe.

    Groups by flooring timestamps to the target TF boundary, then merges
    each group into a single OHLCV candle.

    Args:
        candles_5m: List of 5-minute CandleData objects (chronological order).
        target_tf: Target timeframe string ('15m', '30m', '1h', '4h').

    Returns:
        List of aggregated CandleData objects.
    """
    mult = TF_MULTIPLIERS.get(target_tf)
    if mult is None or mult <= 1:
        return list(candles_5m)

    interval_ms = mult * 5 * 60 * 1000  # target TF in milliseconds
    result: list[CandleData] = []
    bucket: list[CandleData] = []
    current_floor = None

    for c in candles_5m:
        floor = (c.timestamp_ms // interval_ms) * interval_ms
        if current_floor is None:
            current_floor = floor

        if floor != current_floor:
            # Flush the completed bucket
            if bucket:
                result.append(_merge_bucket(bucket, current_floor))
            bucket = [c]
            current_floor = floor
        else:
            bucket.append(c)

    # Flush last bucket (only if complete)
    if len(bucket) >= mult:
        result.append(_merge_bucket(bucket, current_floor))

    return result


def _merge_bucket(bucket: list[CandleData], timestamp_ms: int) -> CandleData:
    """Merge a group of candles into a single aggregated candle."""
    return CandleData(
        timestamp_ms=timestamp_ms,
        open=bucket[0].open,
        high=max(c.high for c in bucket),
        low=min(c.low for c in bucket),
        close=bucket[-1].close,
        volume=sum(c.volume for c in bucket),
    )
