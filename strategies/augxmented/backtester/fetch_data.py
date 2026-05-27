"""
Historical Data Fetcher
=========================
Fetches QQQ/SPY bars from Alpaca (primary) or yfinance (fallback).
Caches results in local SQLite.
"""

import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from strategies.templates.base_strategy import CandleData

DATA_DIR = Path(__file__).parent / "data"
DB_PATH = DATA_DIR / "bars.db"


# ---------------------------------------------------------------------------
# SQLite cache
# ---------------------------------------------------------------------------

def _init_db() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bars (
            symbol TEXT,
            interval TEXT DEFAULT '5m',
            timestamp_ms INTEGER,
            open REAL, high REAL, low REAL, close REAL, volume REAL,
            PRIMARY KEY (symbol, interval, timestamp_ms)
        )
    """)
    conn.commit()
    return conn


def _date_to_ms(date_str: str) -> int:
    return int(
        datetime.strptime(date_str, "%Y-%m-%d")
        .replace(tzinfo=timezone.utc)
        .timestamp() * 1000
    )


def _load_from_cache(conn, symbol, interval, start_date, end_date):
    start_ms = _date_to_ms(start_date)
    end_ms = _date_to_ms(end_date) + 86_400_000
    rows = conn.execute(
        """SELECT timestamp_ms, open, high, low, close, volume
           FROM bars
           WHERE symbol=? AND interval=? AND timestamp_ms>=? AND timestamp_ms<=?
           ORDER BY timestamp_ms""",
        (symbol, interval, start_ms, end_ms),
    ).fetchall()
    return [
        CandleData(timestamp_ms=r[0], open=r[1], high=r[2],
                    low=r[3], close=r[4], volume=r[5])
        for r in rows
    ]


def _save_to_cache(conn, rows, interval):
    if rows:
        conn.executemany(
            "INSERT OR REPLACE INTO bars (symbol,interval,timestamp_ms,open,high,low,close,volume) "
            "VALUES (?,?,?,?,?,?,?,?)",
            [(r[0], interval, *r[1:]) for r in rows],
        )
        conn.commit()


# ---------------------------------------------------------------------------
# yfinance fetcher (primary — free, no API key needed)
# ---------------------------------------------------------------------------

def _fetch_yfinance(symbol: str, start_date: str, end_date: str,
                    interval: str = "5m") -> list[tuple]:
    """Fetch bars via yfinance. Returns list of (symbol, ts_ms, o, h, l, c, v)."""
    import yfinance as yf

    rows = []

    if interval == "5m":
        # yfinance limits 5m data to last 60 days — use period='60d'
        print(f"  {symbol}: fetching {interval} bars via yfinance (max 60 days)...")
        df = yf.download(symbol, period="60d", interval="5m", progress=False)
    else:
        print(f"  {symbol}: fetching {interval} bars via yfinance ({start_date} → {end_date})...")
        df = yf.download(symbol, start=start_date, end=end_date,
                         interval=interval, progress=False)

    if df.empty:
        print(f"  {symbol}: no data returned from yfinance")
        return rows

    # Flatten MultiIndex columns if present
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)

    for ts, row in df.iterrows():
        ts_ms = int(ts.timestamp() * 1000)
        rows.append((
            symbol, ts_ms,
            float(row["Open"]), float(row["High"]),
            float(row["Low"]), float(row["Close"]),
            float(row["Volume"]),
        ))

    print(f"  {symbol}: {len(rows):,} bars fetched")
    return rows


# ---------------------------------------------------------------------------
# Alpaca fetcher (alternative — needs valid API keys)
# ---------------------------------------------------------------------------

def _fetch_alpaca(symbol: str, start_date: str, end_date: str) -> list[tuple]:
    """Fetch 5m bars from Alpaca. Returns list of (symbol, ts_ms, o, h, l, c, v)."""
    import alpaca_trade_api as tradeapi

    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")
    if not api_key or not secret_key:
        return []

    paper = os.getenv("ALPACA_PAPER", "true").lower() == "true"
    base_url = "https://paper-api.alpaca.markets" if paper else "https://api.alpaca.markets"
    api = tradeapi.REST(api_key, secret_key, base_url, api_version='v2')

    # Quick auth check
    try:
        api.get_account()
    except Exception:
        print(f"  Alpaca auth failed — falling back to yfinance")
        return []

    print(f"  {symbol}: fetching 5m bars from Alpaca ({start_date} → {end_date})...")
    tf = tradeapi.TimeFrame(5, tradeapi.TimeFrameUnit.Minute)
    all_rows = []
    current = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    while current < end_dt:
        chunk_end = min(current + timedelta(days=30), end_dt)
        try:
            df = api.get_bars(
                symbol, tf,
                start=current.strftime("%Y-%m-%d"),
                end=chunk_end.strftime("%Y-%m-%d"),
                feed="iex", limit=10000,
            ).df
            for ts, row in df.iterrows():
                ts_val = ts[-1] if isinstance(ts, tuple) else ts
                all_rows.append((
                    symbol, int(ts_val.timestamp() * 1000),
                    float(row["open"]), float(row["high"]),
                    float(row["low"]), float(row["close"]),
                    float(row["volume"]),
                ))
            print(f"    {current.strftime('%Y-%m-%d')} → {chunk_end.strftime('%Y-%m-%d')}  "
                  f"{len(df):,} bars")
        except Exception as e:
            print(f"    {current.strftime('%Y-%m-%d')} → {chunk_end.strftime('%Y-%m-%d')}  "
                  f"ERROR: {e}")
        current = chunk_end
        time.sleep(0.3)

    print(f"  {symbol}: {len(all_rows):,} bars from Alpaca")
    return all_rows


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_bars(
    symbol: str,
    start_date: str,
    end_date: str,
    interval: str = "5m",
    force_refresh: bool = False,
) -> list[CandleData]:
    """
    Fetch bars with caching. Tries Alpaca first, falls back to yfinance.

    Args:
        symbol: Ticker ('QQQ', 'SPY').
        start_date: 'YYYY-MM-DD'.
        end_date: 'YYYY-MM-DD'.
        interval: '5m', '15m', '1h', etc.
        force_refresh: Skip cache.

    Returns:
        List of CandleData sorted by timestamp.
    """
    conn = _init_db()

    if not force_refresh:
        candles = _load_from_cache(conn, symbol, interval, start_date, end_date)
        if candles:
            print(f"  {symbol} ({interval}): {len(candles):,} bars from cache")
            conn.close()
            return candles

    # Try Alpaca first (only for 5m, since that's what it's configured for)
    rows = []
    if interval == "5m":
        rows = _fetch_alpaca(symbol, start_date, end_date)

    # Fall back to yfinance
    if not rows:
        rows = _fetch_yfinance(symbol, start_date, end_date, interval=interval)

    _save_to_cache(conn, rows, interval)
    candles = _load_from_cache(conn, symbol, interval, start_date, end_date)
    conn.close()
    return candles
