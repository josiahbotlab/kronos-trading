#!/usr/bin/env python3
"""
Kronos Trade Journal
=====================
Enriched trade logging for the self-improving feedback loop.

Captures far more context than execution.db's trades table:
- Market regime at entry and exit
- Signal strength and tag
- Candle context (OHLCV + liquidation) at entry and exit
- Slippage (fill_price vs candle.close)
- Duration in seconds

This data feeds:
- Skill file generation (strategy performance by regime)
- Parameter updater (what conditions produce best trades)
- Regime-aware strategy selection
"""

import logging
import sqlite3
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("trade_journal")

DB_PATH = Path(__file__).parent.parent / "data" / "trade_journal.db"


class TradeJournal:
    """
    Enriched trade journal backed by SQLite.

    Usage:
        journal = TradeJournal(timeframe="5m")
        journal.log_entry(strategy_name, symbol, side, signal, candle, fill_price, position, regime)
        journal.log_exit(trade_dict, exit_candle, exit_regime)
        stats = journal.get_stats(strategy="liq_bb_combo", regime="trending_up")
    """

    def __init__(
        self,
        db_path: Path = DB_PATH,
        timeframe: str = "5m",
        mode: str = "paper",
    ):
        self.db_path = db_path
        self.timeframe = timeframe
        self.mode = mode
        self._init_db()

    def _init_db(self):
        """Create tables if they don't exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.execute("PRAGMA journal_mode=WAL")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS open_positions (
                    position_id TEXT PRIMARY KEY,
                    strategy TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    entry_time REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    fill_price REAL NOT NULL,
                    quantity REAL NOT NULL,
                    notional_usd REAL NOT NULL,
                    signal_direction INTEGER,
                    signal_strength REAL,
                    signal_tag TEXT,
                    regime_at_entry TEXT,
                    timeframe TEXT,
                    entry_candle_open REAL,
                    entry_candle_high REAL,
                    entry_candle_low REAL,
                    entry_candle_close REAL,
                    entry_candle_volume REAL,
                    entry_candle_liq_usd REAL,
                    entry_slippage REAL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS closed_trades (
                    position_id TEXT PRIMARY KEY,
                    strategy TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    entry_time REAL NOT NULL,
                    exit_time REAL NOT NULL,
                    duration_seconds REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL NOT NULL,
                    fill_price_entry REAL NOT NULL,
                    fill_price_exit REAL,
                    quantity REAL NOT NULL,
                    notional_usd REAL NOT NULL,
                    pnl_usd REAL NOT NULL,
                    pnl_pct REAL NOT NULL,
                    signal_direction INTEGER,
                    signal_strength REAL,
                    signal_tag TEXT,
                    exit_reason TEXT,
                    regime_at_entry TEXT,
                    regime_at_exit TEXT,
                    timeframe TEXT,
                    entry_candle_open REAL,
                    entry_candle_high REAL,
                    entry_candle_low REAL,
                    entry_candle_close REAL,
                    entry_candle_volume REAL,
                    entry_candle_liq_usd REAL,
                    exit_candle_open REAL,
                    exit_candle_high REAL,
                    exit_candle_low REAL,
                    exit_candle_close REAL,
                    exit_candle_volume REAL,
                    exit_candle_liq_usd REAL,
                    entry_slippage REAL,
                    exit_slippage REAL,
                    mode TEXT DEFAULT 'paper',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.execute("CREATE INDEX IF NOT EXISTS idx_closed_strategy ON closed_trades(strategy)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_closed_regime_entry ON closed_trades(regime_at_entry)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_closed_exit_time ON closed_trades(exit_time)")

            conn.commit()
            conn.close()
            log.info("Trade journal DB initialized")
        except Exception as e:
            log.error(f"Failed to init trade journal DB: {e}")

    def log_entry(
        self,
        strategy_name: str,
        symbol: str,
        side: str,
        signal,       # Signal object
        candle,       # CandleData object
        fill_price: float,
        position,     # LivePosition object
        regime: str,
    ) -> None:
        """Record a trade entry into open_positions."""
        try:
            entry_slippage = fill_price - candle.close

            conn = sqlite3.connect(str(self.db_path))
            conn.execute(
                """INSERT OR REPLACE INTO open_positions
                   (position_id, strategy, symbol, side, entry_time, entry_price,
                    fill_price, quantity, notional_usd, signal_direction,
                    signal_strength, signal_tag, regime_at_entry, timeframe,
                    entry_candle_open, entry_candle_high, entry_candle_low,
                    entry_candle_close, entry_candle_volume, entry_candle_liq_usd,
                    entry_slippage)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    position.id, strategy_name, symbol, side,
                    position.entry_time, position.entry_price,
                    fill_price, position.quantity, position.notional_usd,
                    signal.direction, signal.strength, signal.tag,
                    regime, self.timeframe,
                    candle.open, candle.high, candle.low, candle.close,
                    candle.volume, candle.liquidation_usd,
                    entry_slippage,
                ),
            )
            conn.commit()
            conn.close()
            log.debug(f"Journal entry: {strategy_name} {side} {symbol} regime={regime}")
        except Exception as e:
            log.warning(f"Journal log_entry failed: {e}")

    def log_exit(
        self,
        trade_dict: dict,
        exit_candle=None,   # CandleData or None
        exit_regime: str = "unknown",
    ) -> None:
        """Record a trade exit. Moves from open_positions -> closed_trades."""
        try:
            pos_id = trade_dict["id"]
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row

            # Fetch entry-side data from open_positions
            row = conn.execute(
                "SELECT * FROM open_positions WHERE position_id = ?", (pos_id,)
            ).fetchone()

            exit_time = trade_dict.get("exit_time", time.time())
            exit_price = trade_dict.get("exit_price", 0.0)

            # Exit candle context
            ec_open = exit_candle.open if exit_candle else None
            ec_high = exit_candle.high if exit_candle else None
            ec_low = exit_candle.low if exit_candle else None
            ec_close = exit_candle.close if exit_candle else None
            ec_vol = exit_candle.volume if exit_candle else None
            ec_liq = exit_candle.liquidation_usd if exit_candle else None
            exit_slippage = (exit_price - exit_candle.close) if exit_candle else None

            if row:
                # Full record from entry data + exit data
                entry_time = row["entry_time"]
                duration = exit_time - entry_time

                conn.execute(
                    """INSERT OR REPLACE INTO closed_trades
                       (position_id, strategy, symbol, side, entry_time, exit_time,
                        duration_seconds, entry_price, exit_price, fill_price_entry,
                        fill_price_exit, quantity, notional_usd, pnl_usd, pnl_pct,
                        signal_direction, signal_strength, signal_tag, exit_reason,
                        regime_at_entry, regime_at_exit, timeframe,
                        entry_candle_open, entry_candle_high, entry_candle_low,
                        entry_candle_close, entry_candle_volume, entry_candle_liq_usd,
                        exit_candle_open, exit_candle_high, exit_candle_low,
                        exit_candle_close, exit_candle_volume, exit_candle_liq_usd,
                        entry_slippage, exit_slippage, mode)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        pos_id, row["strategy"], row["symbol"], row["side"],
                        entry_time, exit_time, duration,
                        row["entry_price"], exit_price, row["fill_price"],
                        exit_price,  # fill_price_exit approximated as exit_price
                        row["quantity"], row["notional_usd"],
                        trade_dict.get("pnl_usd", 0), trade_dict.get("pnl_pct", 0),
                        row["signal_direction"], row["signal_strength"], row["signal_tag"],
                        trade_dict.get("tag", ""),
                        row["regime_at_entry"], exit_regime, row["timeframe"],
                        row["entry_candle_open"], row["entry_candle_high"],
                        row["entry_candle_low"], row["entry_candle_close"],
                        row["entry_candle_volume"], row["entry_candle_liq_usd"],
                        ec_open, ec_high, ec_low, ec_close, ec_vol, ec_liq,
                        row["entry_slippage"], exit_slippage, self.mode,
                    ),
                )
                # Remove from open_positions
                conn.execute("DELETE FROM open_positions WHERE position_id = ?", (pos_id,))
            else:
                # No entry record (engine was running before journal existed)
                entry_time = trade_dict.get("entry_time", exit_time)
                duration = exit_time - entry_time

                conn.execute(
                    """INSERT OR REPLACE INTO closed_trades
                       (position_id, strategy, symbol, side, entry_time, exit_time,
                        duration_seconds, entry_price, exit_price, fill_price_entry,
                        fill_price_exit, quantity, notional_usd, pnl_usd, pnl_pct,
                        signal_direction, signal_strength, signal_tag, exit_reason,
                        regime_at_entry, regime_at_exit, timeframe,
                        exit_candle_open, exit_candle_high, exit_candle_low,
                        exit_candle_close, exit_candle_volume, exit_candle_liq_usd,
                        exit_slippage, mode)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        pos_id, trade_dict.get("strategy", ""),
                        trade_dict.get("symbol", ""), trade_dict.get("side", ""),
                        entry_time, exit_time, duration,
                        trade_dict.get("entry_price", 0), exit_price,
                        trade_dict.get("entry_price", 0), exit_price,
                        trade_dict.get("quantity", 0), trade_dict.get("notional_usd", 0),
                        trade_dict.get("pnl_usd", 0), trade_dict.get("pnl_pct", 0),
                        None, None, None,
                        trade_dict.get("tag", ""),
                        "unknown", exit_regime, self.timeframe,
                        ec_open, ec_high, ec_low, ec_close, ec_vol, ec_liq,
                        exit_slippage, self.mode,
                    ),
                )

            conn.commit()
            conn.close()
            pnl = trade_dict.get("pnl_usd", 0)
            log.debug(f"Journal exit: {pos_id} pnl=${pnl:+.2f} regime={exit_regime}")
        except Exception as e:
            log.warning(f"Journal log_exit failed: {e}")

    def get_stats(
        self,
        strategy: Optional[str] = None,
        regime: Optional[str] = None,
        symbol: Optional[str] = None,
        days: Optional[int] = None,
    ) -> dict:
        """
        Query aggregated trade statistics from closed_trades.

        Returns dict with total_trades, win_rate, avg_pnl, by_regime breakdown, etc.
        """
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row

            where_parts = []
            params = []

            if strategy:
                where_parts.append("strategy = ?")
                params.append(strategy)
            if regime:
                where_parts.append("regime_at_entry = ?")
                params.append(regime)
            if symbol:
                where_parts.append("symbol = ?")
                params.append(symbol)
            if days:
                cutoff = time.time() - days * 86400
                where_parts.append("exit_time > ?")
                params.append(cutoff)

            where = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

            # Main aggregation
            row = conn.execute(
                f"""SELECT
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) as win_count,
                    SUM(pnl_usd) as total_pnl_usd,
                    AVG(pnl_usd) as avg_pnl_usd,
                    AVG(pnl_pct) as avg_pnl_pct,
                    AVG(duration_seconds) as avg_duration_seconds,
                    AVG(entry_slippage) as avg_entry_slippage,
                    AVG(exit_slippage) as avg_exit_slippage
                FROM closed_trades {where}""",
                params,
            ).fetchone()

            total = row["total_trades"] or 0
            wins = row["win_count"] or 0

            result = {
                "total_trades": total,
                "win_count": wins,
                "win_rate": wins / total if total > 0 else 0.0,
                "total_pnl_usd": row["total_pnl_usd"] or 0.0,
                "avg_pnl_usd": row["avg_pnl_usd"] or 0.0,
                "avg_pnl_pct": row["avg_pnl_pct"] or 0.0,
                "avg_duration_seconds": row["avg_duration_seconds"] or 0.0,
                "avg_entry_slippage": row["avg_entry_slippage"] or 0.0,
                "avg_exit_slippage": row["avg_exit_slippage"] or 0.0,
            }

            # By regime breakdown
            regime_rows = conn.execute(
                f"""SELECT regime_at_entry,
                    COUNT(*) as trades,
                    SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) as wins,
                    AVG(pnl_pct) as avg_pnl_pct
                FROM closed_trades {where}
                GROUP BY regime_at_entry""",
                params,
            ).fetchall()

            result["by_regime"] = {}
            for r in regime_rows:
                regime_name = r["regime_at_entry"] or "unknown"
                t = r["trades"]
                result["by_regime"][regime_name] = {
                    "trades": t,
                    "win_rate": r["wins"] / t if t > 0 else 0.0,
                    "avg_pnl_pct": r["avg_pnl_pct"] or 0.0,
                }

            # By signal tag breakdown
            tag_rows = conn.execute(
                f"""SELECT signal_tag,
                    COUNT(*) as trades,
                    SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) as wins,
                    AVG(pnl_pct) as avg_pnl_pct
                FROM closed_trades {where}
                GROUP BY signal_tag""",
                params,
            ).fetchall()

            result["by_tag"] = {}
            for r in tag_rows:
                tag = r["signal_tag"] or "unknown"
                t = r["trades"]
                result["by_tag"][tag] = {
                    "trades": t,
                    "win_rate": r["wins"] / t if t > 0 else 0.0,
                    "avg_pnl_pct": r["avg_pnl_pct"] or 0.0,
                }

            conn.close()
            return result

        except Exception as e:
            log.warning(f"Journal get_stats failed: {e}")
            return {
                "total_trades": 0, "win_count": 0, "win_rate": 0.0,
                "total_pnl_usd": 0.0, "avg_pnl_usd": 0.0, "avg_pnl_pct": 0.0,
                "avg_duration_seconds": 0.0, "avg_entry_slippage": 0.0,
                "avg_exit_slippage": 0.0, "by_regime": {}, "by_tag": {},
            }

    def get_open_count(self) -> int:
        """Count currently open journal entries."""
        try:
            conn = sqlite3.connect(str(self.db_path))
            count = conn.execute("SELECT COUNT(*) FROM open_positions").fetchone()[0]
            conn.close()
            return count
        except Exception:
            return 0

    def get_closed_count(self) -> int:
        """Count total closed trades in journal."""
        try:
            conn = sqlite3.connect(str(self.db_path))
            count = conn.execute("SELECT COUNT(*) FROM closed_trades").fetchone()[0]
            conn.close()
            return count
        except Exception:
            return 0
