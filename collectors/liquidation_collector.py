#!/usr/bin/env python3
"""
Kronos Liquidation Collector
=============================
Streams BTC forced liquidations from BOTH Binance Futures and Bybit V5,
filters BTC perp only, drops sub-$10k notional events, and stores them in
SQLite for backtesting liquidation cascade strategies.

Data sources:
  - Binance: wss://fstream.binance.com/ws/!forceOrder@arr
  - Bybit:   wss://stream.bybit.com/v5/public/linear  (subscribe allLiquidation.BTCUSDT)

Hourly Telegram summary posts long/short counts and notional.

Usage:
    python liquidation_collector.py
"""

import asyncio
import json
import logging
import signal
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

try:
    import websockets
except ImportError:
    print("Install deps: pip install websockets")
    sys.exit(1)

# Telegram notifier (urllib only, no external deps)
sys.path.insert(0, str(Path(__file__).parent.parent))
try:
    from execution.telegram_notifier import TelegramNotifier
except Exception:
    TelegramNotifier = None  # noqa: N806

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BINANCE_WS_URL = "wss://fstream.binance.com/ws/!forceOrder@arr"
BYBIT_WS_URL = "wss://stream.bybit.com/v5/public/linear"
RECONNECT_DELAY = 5            # seconds between reconnect attempts
LOG_INTERVAL = 300             # print stats every 5 min
TELEGRAM_INTERVAL = 86400      # daily summary (was 3600/hourly — cut 2026-05-17 to reduce TG noise)
TELEGRAM_WINDOW_SECONDS = 86400  # how much history the summary covers (must match interval)
BIG_LIQ_THRESHOLD_USD = 1_000_000  # per-event TG alert when single liquidation >= $1M
DB_PATH = Path(__file__).parent.parent / "data" / "liquidations.db"
BATCH_SIZE = 50
BATCH_TIMEOUT = 10
MIN_USD_VALUE = 10_000.0       # drop liquidations below this notional
ALLOWED_SYMBOLS = {"BTCUSDT", "BTCPERP"}  # BTC perp only

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("liq_collector")

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
def init_db(db_path: Path) -> sqlite3.Connection:
    """Open the liquidations DB, ensuring schema + new exchange column.

    PRESERVES existing rows. Uses ALTER TABLE for the new column when missing.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)

    # Performance for write-heavy workload
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-64000")
    conn.execute("PRAGMA busy_timeout=5000")

    # Original table (no-op if it already exists with 324k rows)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS liquidations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp_ms INTEGER NOT NULL,
            timestamp_utc TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            order_type TEXT NOT NULL,
            time_in_force TEXT,
            quantity REAL NOT NULL,
            price REAL NOT NULL,
            avg_price REAL NOT NULL,
            status TEXT NOT NULL,
            last_filled_qty REAL,
            accumulated_qty REAL,
            usd_value REAL NOT NULL,
            collected_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    # Idempotent column add: check PRAGMA, ALTER if missing
    cols = {row[1] for row in conn.execute("PRAGMA table_info(liquidations)").fetchall()}
    if "exchange" not in cols:
        log.info("Adding 'exchange' column to liquidations (default 'binance')")
        conn.execute(
            "ALTER TABLE liquidations ADD COLUMN exchange TEXT NOT NULL DEFAULT 'binance'"
        )

    # Indexes (idempotent)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_liq_timestamp ON liquidations(timestamp_ms)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_liq_symbol_time ON liquidations(symbol, timestamp_ms)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_liq_usd_value ON liquidations(usd_value)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_liq_side_time ON liquidations(side, timestamp_ms)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_liq_exchange_time ON liquidations(exchange, timestamp_ms)")

    # Cascades view (drop+recreate is fine - it's just a view)
    conn.execute("DROP VIEW IF EXISTS cascade_1m")
    conn.execute("""
        CREATE VIEW cascade_1m AS
        SELECT
            (timestamp_ms / 60000) * 60000 AS window_start_ms,
            symbol,
            exchange,
            COUNT(*) AS event_count,
            SUM(CASE WHEN side = 'BUY' THEN 1 ELSE 0 END) AS short_liqs,
            SUM(CASE WHEN side = 'SELL' THEN 1 ELSE 0 END) AS long_liqs,
            SUM(usd_value) AS total_usd,
            SUM(CASE WHEN side = 'BUY' THEN usd_value ELSE 0 END) AS short_liq_usd,
            SUM(CASE WHEN side = 'SELL' THEN usd_value ELSE 0 END) AS long_liq_usd,
            MAX(usd_value) AS max_single_liq,
            AVG(usd_value) AS avg_liq_size
        FROM liquidations
        GROUP BY window_start_ms, symbol, exchange
    """)

    conn.commit()
    log.info(f"Database ready: {db_path}")
    return conn


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------
class LiquidationCollector:
    """Multi-exchange BTC liquidation collector."""

    def __init__(self, db_path: Path = DB_PATH):
        self.conn = init_db(db_path)
        self.db_lock = asyncio.Lock()
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="liq-db")
        self.running = True

        # Per-exchange batches (separated so DB writes don't compete)
        self.batch: list[tuple] = []
        self.last_flush = time.time()

        # Stats
        self.session_events = 0
        self.session_usd = 0.0
        self.session_start = time.time()
        self.last_log = time.time()
        self.largest_liq = 0.0
        self.largest_liq_symbol = ""

        # Telegram
        self.telegram = TelegramNotifier() if TelegramNotifier else None

    # ------------------------------------------------------------------
    # Parsers
    # ------------------------------------------------------------------
    def parse_binance(self, data: dict) -> tuple | None:
        """Parse a Binance forceOrder event.

        Binance side semantics (Binance "S" field):
          - S=SELL  => the liquidator sold => a LONG was liquidated
          - S=BUY   => the liquidator bought => a SHORT was liquidated
        We store side verbatim ("BUY"/"SELL") to preserve historical convention.
        """
        try:
            order = data.get("o", {})
            symbol = order.get("s", "")
            if symbol not in ALLOWED_SYMBOLS:
                return None
            side = order.get("S", "")
            order_type = order.get("o", "")
            tif = order.get("f", "")
            qty = float(order.get("q", 0))
            price = float(order.get("p", 0))
            avg_price = float(order.get("ap", 0))
            status = order.get("X", "")
            last_qty = float(order.get("l", 0))
            acc_qty = float(order.get("z", 0))
            ts_ms = int(order.get("T", 0))

            use_price = avg_price if avg_price > 0 else price
            usd_value = qty * use_price
            if usd_value < MIN_USD_VALUE:
                return None

            ts_utc = datetime.fromtimestamp(
                ts_ms / 1000, tz=timezone.utc
            ).strftime("%Y-%m-%d %H:%M:%S")

            return (
                ts_ms, ts_utc, symbol, side, order_type, tif,
                qty, price, avg_price, status, last_qty, acc_qty, usd_value,
                "binance",
            )
        except (KeyError, ValueError, TypeError) as e:
            log.warning(f"binance parse fail: {e} | data={data}")
            return None

    def parse_bybit(self, payload: dict) -> list[tuple]:
        """Parse a Bybit V5 liquidation event (or list of events).

        Bybit V5 'side' semantics: it reports the side of the LIQUIDATING
        action — i.e., when a long is liquidated, Bybit reports side='Sell'
        (liquidator sells the long position). This matches Binance's "S"
        field semantics exactly. We normalize to upper-case BUY/SELL so the
        existing convention holds:
            side=='SELL' => long liquidated
            side=='BUY'  => short liquidated
        """
        rows: list[tuple] = []
        try:
            data = payload.get("data")
            if data is None:
                return rows
            # Bybit may send dict (single) or list (batched)
            events = data if isinstance(data, list) else [data]
            for ev in events:
                symbol = ev.get("symbol") or ev.get("s") or ""
                if symbol not in ALLOWED_SYMBOLS:
                    continue
                # 'allLiquidation' shape uses 'S'; legacy 'liquidation' used 'side'
                bybit_side = (ev.get("side") or ev.get("S") or "").upper()  # 'BUY' or 'SELL'
                if bybit_side not in ("BUY", "SELL"):
                    continue
                # Mirror Binance semantic (already aligned): liquidator's action
                side = bybit_side

                size = float(ev.get("size") or ev.get("v") or 0)
                price = float(ev.get("price") or ev.get("p") or 0)
                ts_ms = int(
                    ev.get("updatedTime")
                    or ev.get("T")
                    or payload.get("ts")
                    or 0
                )
                if size <= 0 or price <= 0 or ts_ms <= 0:
                    continue
                usd_value = size * price
                if usd_value < MIN_USD_VALUE:
                    continue
                ts_utc = datetime.fromtimestamp(
                    ts_ms / 1000, tz=timezone.utc
                ).strftime("%Y-%m-%d %H:%M:%S")
                # Bybit doesn't expose order_type/tif/status/last/acc — use sane defaults
                rows.append((
                    ts_ms, ts_utc, symbol, side,
                    "LIQUIDATION", "", size, price, price,
                    "FILLED", size, size, usd_value,
                    "bybit",
                ))
        except (KeyError, ValueError, TypeError) as e:
            log.warning(f"bybit parse fail: {e} | payload={payload}")
        return rows

    # ------------------------------------------------------------------
    # DB writes
    # ------------------------------------------------------------------
    def _flush_sync(self, rows: list[tuple]):
        try:
            self.conn.executemany(
                """INSERT INTO liquidations
                   (timestamp_ms, timestamp_utc, symbol, side, order_type,
                    time_in_force, quantity, price, avg_price, status,
                    last_filled_qty, accumulated_qty, usd_value, exchange)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )
            self.conn.commit()
        except sqlite3.Error as e:
            log.error(f"DB write failed: {e}")

    async def flush_batch(self):
        if not self.batch:
            return
        async with self.db_lock:
            rows = self.batch
            self.batch = []
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(self.executor, self._flush_sync, rows)
            self.last_flush = time.time()

    def _record(self, row: tuple):
        usd_value = row[12]
        symbol = row[2]
        side = row[3]
        exch = row[13]
        self.batch.append(row)
        self.session_events += 1
        self.session_usd += usd_value
        if usd_value > self.largest_liq:
            self.largest_liq = usd_value
            self.largest_liq_symbol = (
                f"{symbol}/{exch} ({'SHORT' if side == 'BUY' else 'LONG'})"
            )
        # Per-event Telegram alert for very large single liquidations (added
        # 2026-05-17). Bypasses the daily summary cadence so cascade events
        # surface immediately. Each event over BIG_LIQ_THRESHOLD_USD pings;
        # no per-symbol throttle since these are rare and meaningful.
        if (usd_value >= BIG_LIQ_THRESHOLD_USD
                and self.telegram and self.telegram.enabled):
            try:
                direction = "SHORT" if side == "BUY" else "LONG"
                self.telegram.send(
                    f"\U0001F525 <b>BIG LIQ</b> ${usd_value:,.0f} "
                    f"{symbol} {direction} on {exch}",
                    parse_mode="HTML",
                )
            except Exception as e:
                log.warning(f"big-liq telegram failed: {e}")

    # ------------------------------------------------------------------
    # Stats / logging
    # ------------------------------------------------------------------
    def log_stats(self):
        elapsed = time.time() - self.session_start
        hrs = elapsed / 3600
        rate = self.session_events / max(elapsed, 1) * 60
        try:
            total = self.conn.execute("SELECT COUNT(*) FROM liquidations").fetchone()[0]
        except sqlite3.Error:
            total = "?"
        log.info(
            f"Session: {self.session_events:,} events | "
            f"${self.session_usd:,.0f} total | "
            f"{rate:.1f}/min | "
            f"Largest: ${self.largest_liq:,.0f} ({self.largest_liq_symbol}) | "
            f"DB total: {total:,} | "
            f"Running: {hrs:.1f}h"
        )
        self.last_log = time.time()

    # ------------------------------------------------------------------
    # Stream loops
    # ------------------------------------------------------------------
    @staticmethod
    def _binance_geo_blocked() -> bool:
        """Probe Binance Futures REST: returns True iff this IP is restricted.

        Binance returns HTTP 451 from `b. Eligibility` policy when the
        source IP is in a restricted location (most EU datacenter ranges
        including this Hetzner range as of 2026-02-19). When 451 is
        returned the WS endpoint also accepts connections but delivers
        zero data — silent block. Diagnosed 2026-05-22.

        We probe once at startup and skip _binance_loop if blocked.
        """
        import urllib.request
        import urllib.error
        try:
            req = urllib.request.Request(
                "https://fapi.binance.com/fapi/v1/ping",
                headers={"User-Agent": "kronos-liq-collector/1.0"},
            )
            with urllib.request.urlopen(req, timeout=8) as r:
                # 200 = unrestricted; any non-200 = treat as blocked
                return r.status != 200
        except urllib.error.HTTPError as e:
            return e.code in (451, 403)
        except Exception:
            # Network error — assume blocked to avoid the spammy reconnect loop;
            # next service restart will re-probe.
            return True

    async def _binance_loop(self):
        if self._binance_geo_blocked():
            log.warning(
                "Binance Futures is geo-blocked from this IP (HTTP 451). "
                "Skipping _binance_loop. Bybit liquidation feed remains active. "
                "Will re-probe on next service restart. See CLAUDE.md "
                "(2026-05-22 entry) for context."
            )
            return
        log.info(f"Binance stream: {BINANCE_WS_URL}")
        while self.running:
            try:
                async with websockets.connect(
                    BINANCE_WS_URL,
                    ping_interval=20, ping_timeout=10, close_timeout=5,
                ) as ws:
                    log.info("Connected: Binance Futures")
                    async for raw in ws:
                        if not self.running:
                            break
                        try:
                            data = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        row = self.parse_binance(data)
                        if row is None:
                            continue
                        self._record(row)
                        await self._maybe_flush()
            except websockets.exceptions.ConnectionClosed as e:
                log.warning(f"Binance WS closed: {e}. Reconnect in {RECONNECT_DELAY}s")
            except Exception as e:
                log.error(f"Binance WS error: {e}. Reconnect in {RECONNECT_DELAY}s")
            await self.flush_batch()
            if self.running:
                await asyncio.sleep(RECONNECT_DELAY)

    async def _bybit_loop(self):
        log.info(f"Bybit stream: {BYBIT_WS_URL}")
        # NOTE: 'liquidation.{symbol}' was deprecated by Bybit in March 2025
        # and now returns "handler not found". Use 'allLiquidation.{symbol}'.
        sub_msg = json.dumps({"op": "subscribe", "args": ["allLiquidation.BTCUSDT"]})
        while self.running:
            try:
                async with websockets.connect(
                    BYBIT_WS_URL,
                    ping_interval=20, ping_timeout=10, close_timeout=5,
                ) as ws:
                    await ws.send(sub_msg)
                    log.info("Connected: Bybit V5 (subscribed liquidation.BTCUSDT)")
                    async for raw in ws:
                        if not self.running:
                            break
                        try:
                            payload = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        # Skip control frames (subscribe ack, pong, etc.)
                        topic = payload.get("topic", "")
                        if not (topic.startswith("liquidation") or topic.startswith("allLiquidation")):
                            continue
                        rows = self.parse_bybit(payload)
                        for row in rows:
                            self._record(row)
                        if rows:
                            await self._maybe_flush()
            except websockets.exceptions.ConnectionClosed as e:
                log.warning(f"Bybit WS closed: {e}. Reconnect in {RECONNECT_DELAY}s")
            except Exception as e:
                log.error(f"Bybit WS error: {e}. Reconnect in {RECONNECT_DELAY}s")
            await self.flush_batch()
            if self.running:
                await asyncio.sleep(RECONNECT_DELAY)

    async def _maybe_flush(self):
        now = time.time()
        if len(self.batch) >= BATCH_SIZE or (now - self.last_flush) > BATCH_TIMEOUT:
            await self.flush_batch()
        if (now - self.last_log) > LOG_INTERVAL:
            self.log_stats()

    async def _periodic_flush(self):
        """Safety net: flush partial batches even when streams are quiet."""
        while self.running:
            await asyncio.sleep(BATCH_TIMEOUT)
            await self.flush_batch()

    async def _hourly_telegram(self):
        """Post periodic Telegram summary of liquidations. As of 2026-05-17,
        cadence is DAILY (TELEGRAM_INTERVAL=86400) — was hourly. Method name
        kept for git history continuity even though it's no longer hourly."""
        # Wait one full window before first send so summary is meaningful
        await asyncio.sleep(TELEGRAM_INTERVAL)
        while self.running:
            try:
                cutoff_ms = int((time.time() - TELEGRAM_WINDOW_SECONDS) * 1000)
                row = self.conn.execute(
                    """SELECT
                         SUM(CASE WHEN side = 'SELL' THEN 1 ELSE 0 END),
                         SUM(CASE WHEN side = 'BUY'  THEN 1 ELSE 0 END),
                         COALESCE(SUM(usd_value), 0),
                         COALESCE(MAX(usd_value), 0)
                       FROM liquidations
                       WHERE timestamp_ms >= ?""",
                    (cutoff_ms,),
                ).fetchone()
                longs = int(row[0] or 0)
                shorts = int(row[1] or 0)
                notional = float(row[2] or 0.0)
                largest = float(row[3] or 0.0)
                window_label = (
                    "last 24h" if TELEGRAM_WINDOW_SECONDS == 86400
                    else f"last {TELEGRAM_WINDOW_SECONDS // 3600}h"
                )
                msg = (
                    f"\U0001F4A7 Liquidations {window_label}: "
                    f"{longs} longs / {shorts} shorts / "
                    f"${notional:,.0f} notional | largest ${largest:,.0f}"
                )
                log.info(msg)
                if self.telegram and self.telegram.enabled:
                    self.telegram.send(msg, parse_mode="HTML")
            except Exception as e:
                log.warning(f"telegram summary failed: {e}")
            await asyncio.sleep(TELEGRAM_INTERVAL)

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------
    async def collect(self):
        log.info("Kronos Liquidation Collector starting (Binance + Bybit, BTC only)")
        log.info(f"   DB: {DB_PATH}")
        log.info(f"   Min notional: ${MIN_USD_VALUE:,.0f}")
        log.info(f"   Telegram: {'enabled' if (self.telegram and self.telegram.enabled) else 'disabled'}")

        await asyncio.gather(
            self._binance_loop(),
            self._bybit_loop(),
            self._periodic_flush(),
            self._hourly_telegram(),
            return_exceptions=False,
        )

    def shutdown(self):
        log.info("Shutting down...")
        self.running = False
        # Synchronous final flush from caller side
        try:
            if self.batch:
                self._flush_sync(self.batch)
                self.batch = []
        except Exception:
            pass
        self.log_stats()
        try:
            self.conn.close()
        except Exception:
            pass
        log.info("Database closed. Goodbye.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    collector = LiquidationCollector()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def handle_signal(_sig, _frame):
        collector.running = False
        # Schedule loop stop from main thread via call_soon_threadsafe
        loop.call_soon_threadsafe(loop.stop)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        loop.run_until_complete(collector.collect())
    except (KeyboardInterrupt, RuntimeError):
        pass
    finally:
        collector.shutdown()
        try:
            loop.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
