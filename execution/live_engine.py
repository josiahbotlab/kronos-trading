#!/usr/bin/env python3
"""
Kronos Live Trading Engine
============================
Main execution loop that runs strategies in real-time.

Modes:
- Paper: Simulated trading with real market data
- Live: Real execution on Hyperliquid (future)

Architecture:
1. Fetch latest candle data from price DB
2. Enrich with latest liquidation data
3. Feed to strategy -> get signal
4. Risk check -> position manager
5. Execute via exchange connector
6. Alert via Telegram
7. Sleep until next candle

Usage:
    # Paper trading with liq_bb_combo on BTC 5m
    python live_engine.py --strategy liq_bb_combo --symbol BTC-USD --timeframe 5m

    # Multi-strategy
    python live_engine.py --strategy cascade_ride,liq_bb_combo --symbol BTC-USD

    # With custom capital and risk
    python live_engine.py --strategy liq_bb_combo --capital 5000 --max-dd 10

    # Status check
    python live_engine.py --status
"""

import argparse
import importlib
import json
import logging
import re
import signal
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from execution.position_manager import PositionManager, RiskConfig, LivePosition
from execution.exchange_connector import ExchangeConnector
from execution.telegram_notifier import TelegramNotifier
from strategies.templates.base_strategy import BaseStrategy, CandleData, Signal
from execution.trade_journal import TradeJournal
from execution.regime_detector import detect_regime

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DATA_DIR = Path(__file__).parent.parent / "data"
SKILL_PATH = Path(__file__).parent.parent / "skills" / "strategy_performance.md"
STRATEGY_DIRS = [
    Path(__file__).parent.parent / "strategies" / "momentum",
    Path(__file__).parent.parent / "strategies" / "reversal",
    Path(__file__).parent.parent / "strategies" / "generated",
]

# Default max hold if strategy doesn't define one (288 bars = 24h at 5m)
DEFAULT_MAX_HOLD_BARS = 288

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("engine")

# Timeframe to seconds mapping
TF_SECONDS = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900,
    "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400,
}
TF_MS = {k: v * 1000 for k, v in TF_SECONDS.items()}


# ---------------------------------------------------------------------------
# Strategy Loading
# ---------------------------------------------------------------------------
def load_strategy(name: str, params: dict = None) -> BaseStrategy:
    """Load a strategy by name from the strategies directory."""
    for sdir in STRATEGY_DIRS:
        for py_file in sdir.glob("*.py"):
            if py_file.stem == "__init__":
                continue
            module_name = f"strategies.{sdir.stem}.{py_file.stem}"
            try:
                module = importlib.import_module(module_name)
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (
                        isinstance(attr, type)
                        and issubclass(attr, BaseStrategy)
                        and attr is not BaseStrategy
                    ):
                        instance = attr(**(params or {}))
                        if instance.name == name:
                            return instance
            except Exception:
                continue

    raise ValueError(f"Strategy '{name}' not found")


def list_strategies() -> list[str]:
    """List all available strategy names."""
    names = []
    for sdir in STRATEGY_DIRS:
        for py_file in sdir.glob("*.py"):
            if py_file.stem == "__init__":
                continue
            module_name = f"strategies.{sdir.stem}.{py_file.stem}"
            try:
                module = importlib.import_module(module_name)
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (
                        isinstance(attr, type)
                        and issubclass(attr, BaseStrategy)
                        and attr is not BaseStrategy
                    ):
                        names.append(attr().name)
            except Exception:
                continue
    return names


# ---------------------------------------------------------------------------
# Data Loading (from collectors' DBs)
# ---------------------------------------------------------------------------
def load_recent_candles(
    symbol: str,
    timeframe: str,
    n_candles: int = 500,
) -> list[CandleData]:
    """Load the most recent N candles from prices.db."""
    db_path = DATA_DIR / "prices.db"
    if not db_path.exists():
        return []

    conn = sqlite3.connect(str(db_path))

    # Try new format first (BTC-USD)
    rows = conn.execute(
        """SELECT timestamp_ms, open, high, low, close, volume
           FROM ohlcv
           WHERE symbol = ? AND timeframe = ?
           ORDER BY timestamp_ms DESC
           LIMIT ?""",
        (symbol, timeframe, n_candles),
    ).fetchall()

    # If no data found, try old format (BTC/USDC:USDC) for backward compatibility
    if not rows:
        old_symbol_map = {
            "BTC-USD": "BTC/USDC:USDC",
            "ETH-USD": "ETH/USDC:USDC",
            "SOL-USD": "SOL/USDC:USDC",
            "DOGE-USD": "DOGE/USDC:USDC",
            "XRP-USD": "XRP/USDC:USDC",
            "ADA-USD": "ADA/USDC:USDC",
            "AVAX-USD": "AVAX/USDC:USDC",
            "LINK-USD": "LINK/USDC:USDC",
        }
        old_symbol = old_symbol_map.get(symbol)
        if old_symbol:
            log.warning(f"No data for {symbol}, trying old format {old_symbol}")
            rows = conn.execute(
                """SELECT timestamp_ms, open, high, low, close, volume
                   FROM ohlcv
                   WHERE symbol = ? AND timeframe = ?
                   ORDER BY timestamp_ms DESC
                   LIMIT ?""",
                (old_symbol, timeframe, n_candles),
            ).fetchall()

    conn.close()

    candles = []
    for row in reversed(rows):  # oldest first
        candles.append(CandleData(
            timestamp_ms=row[0],
            open=row[1], high=row[2], low=row[3],
            close=row[4], volume=row[5],
        ))
    return candles


def enrich_candle_liquidations(candle: CandleData, symbol: str, tf_ms: int):
    """Attach liquidation data to a single candle."""
    db_path = DATA_DIR / "liquidations.db"
    if not db_path.exists():
        return

    # Map symbol: BTC-USD -> BTCUSDT (liqs from Binance)
    base = symbol.split("-")[0]
    bn_symbol = f"{base}USDT"

    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        """SELECT
            COALESCE(SUM(usd_value), 0),
            COALESCE(SUM(CASE WHEN side='BUY' THEN usd_value ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN side='SELL' THEN usd_value ELSE 0 END), 0),
            COUNT(*)
        FROM liquidations
        WHERE symbol = ? AND timestamp_ms >= ? AND timestamp_ms < ?""",
        (bn_symbol, candle.timestamp_ms, candle.timestamp_ms + tf_ms),
    ).fetchone()
    conn.close()

    if row:
        candle.liquidation_usd = row[0]
        candle.short_liq_usd = row[1]
        candle.long_liq_usd = row[2]
        candle.liq_count = row[3]


def enrich_candles_batch(candles: list[CandleData], symbol: str, tf_ms: int):
    """Enrich all candles with liquidation data."""
    db_path = DATA_DIR / "liquidations.db"
    if not db_path.exists():
        return

    base = symbol.split("-")[0]
    bn_symbol = f"{base}USDT"

    conn = sqlite3.connect(str(db_path))
    for candle in candles:
        row = conn.execute(
            """SELECT
                COALESCE(SUM(usd_value), 0),
                COALESCE(SUM(CASE WHEN side='BUY' THEN usd_value ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN side='SELL' THEN usd_value ELSE 0 END), 0),
                COUNT(*)
            FROM liquidations
            WHERE symbol = ? AND timestamp_ms >= ? AND timestamp_ms < ?""",
            (bn_symbol, candle.timestamp_ms, candle.timestamp_ms + tf_ms),
        ).fetchone()
        if row:
            candle.liquidation_usd = row[0]
            candle.short_liq_usd = row[1]
            candle.long_liq_usd = row[2]
            candle.liq_count = row[3]
    conn.close()


# ---------------------------------------------------------------------------
# Hard ceilings from 210-trade manual analysis (2026-04-16).
# Duplicated here so live_engine enforces them even if skill_updater pushes
# a stale recommendation. Tuner may TIGHTEN below these values but never
# LOOSEN above them.
# ---------------------------------------------------------------------------
PARAM_MANUAL_OPTIMA = {
    "vwap_mean_reversion": {
        "stop_loss_pct": 0.8,
        "take_profit_pct": 1.2,
        "max_hold_bars": 16,
    },
    "capitulation_reversal": {
        "stop_loss_pct": 1.5,
        "take_profit_pct": 1.8,
        "trailing_stop_pct": 1.2,
        "trail_after_bars": 6,
        "max_hold_bars": 18,
    },
    "mtf_mean_reversion": {
        "stop_loss_pct": 1.2,
        "take_profit_pct": 1.2,
        "max_hold_bars": 24,
    },
}


# Directional bias system removed 2026-05-20 (see CLAUDE.md). Gate 2
# (STRATEGY_BLOCKED_REGIMES_LONG below) is the active regime filter.

# ---------------------------------------------------------------------------
# Strategy-specific directional regime gates (added 2026-05-12).
#
# Moved here from strategies/generated/vwap_mean_reversion.py — the strategy
# read regime from data/directional_bias.json which is a daily 00:05 UTC
# snapshot, so the gate operated on a regime label up to ~24h stale. The
# engine already recomputes `regime` fresh each cycle via `_get_regime()`,
# so the gate belongs here (single source of truth).
#
# Audit finding 2026-05-11: 5 of 6 recent big losers (>$5) on
# vwap_mean_reversion were LONGs entered while regime=trending_down. The
# very first qualifying signal post-deployment (2026-05-11 21:23 UTC) was
# also a LONG in trending_down — entered because the stale gate read
# "volatile" from the bias file. This live-regime version closes that gap.
# ---------------------------------------------------------------------------
STRATEGY_BLOCKED_REGIMES_LONG: dict[str, frozenset[str]] = {
    "vwap_mean_reversion": frozenset({"trending_down"}),
}

# ---------------------------------------------------------------------------
# Market-intel (ai4trade.ai) context + soft sizing gate (added 2026-05-12).
# Snapshots refresh ≤ once per 15 min upstream, so they're context-only:
# never a hard block, just a size-down when macro AND ETF flows both point
# bearish. Fail-open: any fetch failure → full size, no log noise.
# Toggle off with MARKET_INTEL_ENABLED = False here.
# ---------------------------------------------------------------------------
MARKET_INTEL_ENABLED = True
MARKET_INTEL_CONTEXT_LOG_INTERVAL_SEC = 4 * 3600  # 4h
MARKET_INTEL_SIZE_DOWN_FACTOR = 0.75              # -25% on bearish+negative ETF

try:
    from utils.market_intel import (  # noqa: E402
        fetch_macro_signals,
        fetch_etf_flows,
        compute_size_multiplier,
        format_context_log,
    )
except Exception as _e:  # noqa: BLE001
    log.warning("market_intel import failed: %s — gate will be no-op", _e)
    fetch_macro_signals = lambda: None  # noqa: E731
    fetch_etf_flows = lambda: None  # noqa: E731
    compute_size_multiplier = lambda *a, **k: (1.0, "market_intel disabled")  # noqa: E731
    format_context_log = lambda: ["[MARKET INTEL] disabled (import failed)"]  # noqa: E731


# get_directional_bias() removed 2026-05-20. The Moonshot daily bias job
# was producing snapshots up to ~24h stale by the time the engine read
# them, and STRATEGY_BLOCKED_REGIMES_LONG already handles the regime gate
# from fresh per-cycle `_get_regime()` data. Bias snapshots are read by
# nothing now.


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
class LiveEngine:
    """
    Main trading engine loop.

    Runs one or more strategies against real-time data,
    manages positions through the position manager,
    and executes via the exchange connector.
    """

    def __init__(
        self,
        strategies: list[tuple[str, BaseStrategy]],  # (symbol, strategy) pairs
        timeframe: str = "5m",
        capital: float = 1000.0,
        paper: bool = True,
        risk_config: RiskConfig = None,
        status_interval: int = 86400,  # send TG status once per day (was 3600/hr — cut 2026-05-17 to reduce Telegram noise; daily summary still fires via kronos-daily-summary.timer)
    ):
        self.strategies = strategies
        self.timeframe = timeframe
        self.tf_ms = TF_MS.get(timeframe, 300000)
        self.tf_seconds = TF_SECONDS.get(timeframe, 300)
        self.paper = paper
        self.running = False

        # Per-strategy capital allocation (equal split)
        n_strategies = len(set(s.name for _, s in strategies))
        adjusted_risk = risk_config or RiskConfig()
        if n_strategies > 1:
            adjusted_risk.max_position_pct = 1.0 / n_strategies
            adjusted_risk.max_total_exposure_pct = min(
                adjusted_risk.max_total_exposure_pct,
                adjusted_risk.max_position_pct * n_strategies,
            )
            log.info(f'Capital allocation: {n_strategies} strategies, '
                     f'{adjusted_risk.max_position_pct*100:.1f}% per strategy')

        # Components
        self.position_mgr = PositionManager(
            initial_capital=capital,
            risk_config=adjusted_risk,
            paper=paper,
        )
        self.exchange = ExchangeConnector(paper=paper)
        self.telegram = TelegramNotifier()
        self.journal = TradeJournal(
            timeframe=timeframe,
            mode="paper" if paper else "live",
        )

        # Regime selector state (Component 2d)
        self._last_regime = {}          # key -> last seen regime
        self._regime_cache = {}         # parsed skill file matrix
        self._regime_cache_mtime = 0.0  # skill file mtime for cache invalidation

        # Self-tune state (Component 2g)
        self._self_tune_enabled = True
        self._tune_state = {}           # strategy -> {changes, consec_losses, trades_since}
        self._tune_db_path = DATA_DIR / "trade_journal.db"

        # State
        self.last_candle_ts: dict[str, int] = {}  # symbol -> last processed candle ts
        self.strategy_histories: dict[str, list[CandleData]] = {}  # key -> candle history
        self.last_status_time = 0.0
        self.status_interval = status_interval
        self.cycle_count = 0
        self._last_market_intel_log = 0.0  # wall-clock; re-log every 4h

    def _strategy_key(self, symbol: str, strategy: BaseStrategy) -> str:
        return f"{strategy.name}_{symbol}"

    def _get_regime(self, strategy: BaseStrategy) -> str:
        """Get current market regime from strategy's candle history."""
        return detect_regime(strategy._candle_history)

    def _load_regime_matrix(self) -> dict:
        """Parse regime performance matrix from skill file. Cached by mtime."""
        try:
            if not SKILL_PATH.exists():
                return {}

            mtime = SKILL_PATH.stat().st_mtime
            if mtime == self._regime_cache_mtime and self._regime_cache:
                return self._regime_cache

            text = SKILL_PATH.read_text()
            matrix = {}
            in_matrix = False
            headers = []

            for line in text.split("\n"):
                if "## Regime Performance Matrix" in line:
                    in_matrix = True
                    continue
                if in_matrix and line.startswith("## "):
                    break
                if not in_matrix or not line.startswith("|"):
                    continue

                cells = [c.strip() for c in line.split("|")[1:-1]]
                if not cells:
                    continue

                if cells[0] == "Strategy":
                    headers = cells[1:]
                    continue
                if cells[0].startswith("---") or cells[0].startswith("-"):
                    continue

                strat_name = cells[0].strip()
                matrix[strat_name] = {}
                for i, cell in enumerate(cells[1:]):
                    if i >= len(headers):
                        break
                    regime = headers[i].strip()
                    m = re.match(r"(\d+)%\s*\((\d+)\)", cell.strip())
                    if m:
                        matrix[strat_name][regime] = {
                            "win_rate": int(m.group(1)) / 100.0,
                            "trades": int(m.group(2)),
                        }

            self._regime_cache = matrix
            self._regime_cache_mtime = mtime
            return matrix
        except Exception as e:
            log.debug(f"Regime matrix parse error: {e}")
            return self._regime_cache or {}

    def _is_strategy_qualified(self, strategy_name: str, regime: str) -> tuple:
        """Check if strategy is qualified for the current regime.

        Returns (allowed: bool, reason: str).
        Rules:
          - No skill data or no strategy entry -> allow (need data)
          - < 5 trades in this regime -> allow (insufficient sample)
          - Win rate >= 45% with n >= 5 -> allow
          - Otherwise -> block
        """
        matrix = self._load_regime_matrix()
        if not matrix:
            return True, "no skill data yet"

        strat_data = matrix.get(strategy_name)
        if not strat_data:
            return True, "no trade history for strategy"

        regime_data = strat_data.get(regime)
        if not regime_data:
            return True, f"no data in {regime}"

        trades = regime_data["trades"]
        wr = regime_data["win_rate"]

        if trades < 5:
            return True, f"insufficient data ({trades} trades in {regime})"

        if wr >= 0.45:
            return True, f"qualified (WR={wr:.0%}, n={trades} in {regime})"

        return False, f"blocked (WR={wr:.0%}, n={trades} in {regime})"

    # ------------------------------------------------------------------
    # Self-Tune: Parameter auto-tuning (Component 2g)
    # ------------------------------------------------------------------

    def _init_param_tables(self):
        """Ensure parameter tables exist in trade_journal.db."""
        try:
            conn = sqlite3.connect(str(self._tune_db_path))
            conn.execute("""
                CREATE TABLE IF NOT EXISTS parameter_recommendations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy TEXT NOT NULL,
                    parameter TEXT NOT NULL,
                    current_value REAL NOT NULL,
                    recommended_value REAL NOT NULL,
                    evidence TEXT,
                    trades_analyzed INTEGER,
                    expected_improvement TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    applied_at TEXT,
                    reverted_at TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS parameter_changes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    parameter TEXT NOT NULL,
                    old_value REAL NOT NULL,
                    new_value REAL NOT NULL,
                    reason TEXT,
                    recommendation_id INTEGER,
                    trades_analyzed INTEGER,
                    auto_or_manual TEXT DEFAULT 'auto',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
            conn.close()
        except Exception as e:
            log.warning(f"Self-tune: init tables failed: {e}")

    def _apply_pending_params(self):
        """Check for and apply pending parameter recommendations from DB."""
        if not self._self_tune_enabled:
            return
        try:
            if not self._tune_db_path.exists():
                return
            conn = sqlite3.connect(str(self._tune_db_path))
            conn.row_factory = sqlite3.Row

            rows = conn.execute(
                "SELECT * FROM parameter_recommendations WHERE status = 'pending' ORDER BY id"
            ).fetchall()

            if not rows:
                conn.close()
                return

            now = datetime.now(timezone.utc).isoformat()

            for row in rows:
                rec_id = row["id"]
                strat_name = row["strategy"]
                param_name = row["parameter"]
                recommended = row["recommended_value"]

                # Find strategy instance
                strategy = None
                for sym, s in self.strategies:
                    if s.name == strat_name:
                        strategy = s
                        break

                if not strategy:
                    log.info(f"Self-tune: strategy '{strat_name}' not loaded, skipping rec {rec_id}")
                    continue

                current = strategy.get_param(param_name)
                if current is None:
                    log.info(f"Self-tune: param '{param_name}' not on {strat_name}, skipping")
                    continue

                # Cap at 20% change from current
                if abs(current) > 1e-8:
                    lower = current * 0.80
                    upper = current * 1.20
                    if lower > upper:
                        lower, upper = upper, lower
                    clamped = max(lower, min(upper, recommended))
                else:
                    clamped = recommended

                # Round to same precision as current
                if isinstance(current, int):
                    clamped = round(clamped)
                else:
                    clamped = round(clamped, 2)

                # Manual-optimum ceiling — never loosen past 210-trade optimum.
                # Guards against runaway tuning where analysis baseline drifts
                # upward via stale parameter_changes rows.
                ceiling = PARAM_MANUAL_OPTIMA.get(strat_name, {}).get(param_name)
                if ceiling is not None and clamped > ceiling:
                    log.warning(
                        f"Self-tune CEILING: {strat_name}.{param_name} "
                        f"{clamped} -> {ceiling} (manual optimum, recommendation "
                        f"{recommended} rejected as loosening)"
                    )
                    clamped = ceiling
                    # If we're already at the ceiling, don't bother applying
                    if abs(clamped - current) < 1e-6:
                        conn.execute(
                            "UPDATE parameter_recommendations SET status = 'rejected_ceiling', "
                            "applied_at = ? WHERE id = ?",
                            (now, rec_id),
                        )
                        continue

                # Apply
                strategy.set_param(param_name, clamped)
                log.info(
                    f"Self-tune APPLIED: {strat_name}.{param_name} "
                    f"{current} -> {clamped} (recommended: {recommended})"
                )

                # Update DB
                conn.execute(
                    "UPDATE parameter_recommendations SET status = 'applied', applied_at = ? WHERE id = ?",
                    (now, rec_id),
                )
                conn.execute(
                    """INSERT INTO parameter_changes
                       (timestamp, strategy, parameter, old_value, new_value,
                        reason, recommendation_id, trades_analyzed, auto_or_manual)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'auto')""",
                    (now, strat_name, param_name, current, clamped,
                     row["evidence"], rec_id, row["trades_analyzed"]),
                )

                # Track for revert
                if strat_name not in self._tune_state:
                    self._tune_state[strat_name] = {
                        "changes": [], "consec_losses": 0, "trades_since": 0,
                    }
                self._tune_state[strat_name]["changes"].append({
                    "param": param_name, "old_value": current,
                    "new_value": clamped, "rec_id": rec_id,
                })
                self._tune_state[strat_name]["consec_losses"] = 0
                self._tune_state[strat_name]["trades_since"] = 0

            conn.commit()
            conn.close()
        except Exception as e:
            log.warning(f"Self-tune: apply error: {e}")

    def _check_param_revert(self, trade: dict):
        """Check if recent param changes should be reverted (5 consecutive losses)."""
        if not self._self_tune_enabled:
            return
        try:
            strat_name = trade.get("strategy", "")
            if strat_name not in self._tune_state:
                return

            state = self._tune_state[strat_name]
            pnl = trade.get("pnl_usd", 0)
            state["trades_since"] += 1

            if pnl <= 0:
                state["consec_losses"] += 1
            else:
                state["consec_losses"] = 0

            if state["consec_losses"] >= 5:
                log.warning(
                    f"Self-tune REVERT: {strat_name} hit {state['consec_losses']} "
                    f"consecutive losses after param changes"
                )
                self._revert_params(strat_name, state)
        except Exception as e:
            log.debug(f"Self-tune revert check error: {e}")

    def _revert_params(self, strat_name: str, state: dict):
        """Revert all parameter changes for a strategy."""
        try:
            strategy = None
            for sym, s in self.strategies:
                if s.name == strat_name:
                    strategy = s
                    break

            if not strategy:
                return

            conn = sqlite3.connect(str(self._tune_db_path))
            now = datetime.now(timezone.utc).isoformat()

            for change in state["changes"]:
                old_val = change["old_value"]
                strategy.set_param(change["param"], old_val)
                log.info(
                    f"Self-tune REVERTED: {strat_name}.{change['param']} "
                    f"-> {old_val}"
                )

                if change.get("rec_id"):
                    conn.execute(
                        "UPDATE parameter_recommendations SET status = 'reverted', reverted_at = ? WHERE id = ?",
                        (now, change["rec_id"]),
                    )

                conn.execute(
                    """INSERT INTO parameter_changes
                       (timestamp, strategy, parameter, old_value, new_value,
                        reason, recommendation_id, auto_or_manual)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 'auto')""",
                    (now, strat_name, change["param"], change["new_value"], old_val,
                     f"auto-reverted after {state['consec_losses']} consecutive losses",
                     change.get("rec_id")),
                )

            conn.commit()
            conn.close()

            del self._tune_state[strat_name]
        except Exception as e:
            log.warning(f"Self-tune revert error: {e}")

    # ------------------------------------------------------------------
    # Position Reconciliation (survive engine restarts)
    # ------------------------------------------------------------------

    def _reconcile_open_positions(self):
        """Reconcile orphaned positions from journal on startup.

        On engine restart, strategies lose their in-memory state (_bars_held,
        _in_trade). This method:
        1. Reads open_positions from trade_journal.db
        2. For positions that exceed max_hold: force close immediately
        3. For valid positions: restore strategy state (_in_trade, _bars_held)
        """
        try:
            db_path = DATA_DIR / "trade_journal.db"
            if not db_path.exists():
                return

            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            positions = conn.execute(
                "SELECT * FROM open_positions"
            ).fetchall()
            conn.close()

            if not positions:
                log.info("Reconciliation: no orphaned positions in journal")
                return

            now = time.time()
            log.info(f"Reconciliation: found {len(positions)} open position(s) in journal")

            for pos in positions:
                pos_id = pos["position_id"]
                strategy_name = pos["strategy"]
                symbol = pos["symbol"]
                side = pos["side"]
                entry_time = pos["entry_time"]
                entry_price = pos["entry_price"]

                elapsed_seconds = now - entry_time
                elapsed_bars = int(elapsed_seconds / self.tf_seconds)
                elapsed_hours = elapsed_seconds / 3600

                # Find matching strategy
                strategy = None
                for sym, s in self.strategies:
                    if s.name == strategy_name and sym == symbol:
                        strategy = s
                        break

                # Get max_hold_bars from strategy params
                max_hold = DEFAULT_MAX_HOLD_BARS
                if strategy:
                    strat_max = strategy.get_param("max_hold_bars")
                    if strat_max is not None:
                        max_hold = int(strat_max)

                log.info(
                    f"  {strategy_name} {side} {symbol} @ ${entry_price:,.2f} | "
                    f"held {elapsed_hours:.1f}h ({elapsed_bars} bars) | "
                    f"max_hold={max_hold} bars"
                )

                if elapsed_bars > max_hold:
                    # Force close — position exceeded max_hold
                    self._force_close_orphan(
                        pos, strategy, reason="orphan_max_hold_exceeded"
                    )
                else:
                    # Restore strategy state
                    self._restore_strategy_state(
                        strategy, side, elapsed_bars, entry_price
                    )

        except Exception as e:
            log.error(f"Reconciliation error: {e}", exc_info=True)

    def _force_close_orphan(self, pos_row, strategy, reason: str):
        """Force close an orphaned position and log the exit."""
        try:
            pos_id = pos_row["position_id"]
            strategy_name = pos_row["strategy"]
            symbol = pos_row["symbol"]
            side = pos_row["side"]
            entry_price = pos_row["entry_price"]
            entry_time = pos_row["entry_time"]
            quantity = pos_row["quantity"]
            notional = pos_row["notional_usd"]

            # Get current price
            current_price = self.exchange.get_price(symbol)
            if not current_price:
                log.warning(f"  Cannot get price for {symbol}, skipping force close")
                return

            # Calculate PnL
            if side == "long":
                pnl_usd = (current_price - entry_price) * quantity
            else:
                pnl_usd = (entry_price - current_price) * quantity
            pnl_pct = (pnl_usd / notional * 100) if notional > 0 else 0.0

            exit_time = time.time()
            duration = exit_time - entry_time

            log.info(
                f"  FORCE CLOSE: {strategy_name} {side} {symbol} | "
                f"entry=${entry_price:,.2f} exit=${current_price:,.2f} | "
                f"PnL=${pnl_usd:+.2f} ({pnl_pct:+.1f}%) | reason={reason}"
            )

            # Build trade dict for journal.log_exit
            trade_dict = {
                "id": pos_id,
                "strategy": strategy_name,
                "symbol": symbol,
                "side": side,
                "entry_price": entry_price,
                "entry_time": entry_time,
                "exit_price": current_price,
                "exit_time": exit_time,
                "quantity": quantity,
                "notional_usd": notional,
                "pnl_usd": pnl_usd,
                "pnl_pct": pnl_pct,
                "tag": reason,
            }

            # Detect regime for exit
            exit_regime = "unknown"
            if strategy:
                try:
                    exit_regime = detect_regime(strategy._candle_history)
                except Exception:
                    pass

            self.journal.log_exit(trade_dict, None, exit_regime)

            # Telegram notification
            self.telegram.send_trade_close({
                **trade_dict,
                "reason": reason,
                "duration_seconds": duration,
            })

            # Reset strategy state if available
            if strategy and hasattr(strategy, "_in_trade"):
                strategy._in_trade = False
                strategy._bars_held = 0

        except Exception as e:
            log.error(f"  Force close failed for {pos_row['position_id']}: {e}")

    def _restore_strategy_state(self, strategy, side, elapsed_bars, entry_price):
        """Restore strategy internal state for a surviving position."""
        if strategy is None:
            return

        if hasattr(strategy, "_in_trade"):
            strategy._in_trade = True
            log.info(f"    Restored _in_trade=True")

        if hasattr(strategy, "_bars_held"):
            strategy._bars_held = elapsed_bars
            log.info(f"    Restored _bars_held={elapsed_bars}")

        if hasattr(strategy, "_trade_direction"):
            direction = 1 if side == "long" else -1
            strategy._trade_direction = direction
            log.info(f"    Restored _trade_direction={direction}")

        if hasattr(strategy, "_peak"):
            strategy._peak = entry_price
        if hasattr(strategy, "_trough"):
            strategy._trough = entry_price

    def _check_orphan_positions(self):
        """Safety check: force close any position held > 2x max_hold in real time.

        Called every cycle in the main loop. Catches orphans even if the
        strategy's bar counter gets lost again after reconciliation.
        """
        try:
            db_path = DATA_DIR / "trade_journal.db"
            if not db_path.exists():
                return

            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            positions = conn.execute(
                "SELECT * FROM open_positions"
            ).fetchall()
            conn.close()

            if not positions:
                return

            now = time.time()

            for pos in positions:
                strategy_name = pos["strategy"]
                entry_time = pos["entry_time"]
                elapsed_seconds = now - entry_time
                elapsed_bars = int(elapsed_seconds / self.tf_seconds)

                # Find strategy and get max_hold
                strategy = None
                for sym, s in self.strategies:
                    if s.name == strategy_name and sym == pos["symbol"]:
                        strategy = s
                        break

                max_hold = DEFAULT_MAX_HOLD_BARS
                if strategy:
                    strat_max = strategy.get_param("max_hold_bars")
                    if strat_max is not None:
                        max_hold = int(strat_max)

                safety_limit = max_hold * 2

                if elapsed_bars > safety_limit:
                    hours = elapsed_seconds / 3600
                    log.warning(
                        f"Orphan safety: {strategy_name} held {hours:.1f}h "
                        f"({elapsed_bars} bars > 2x max_hold={max_hold})"
                    )
                    self._force_close_orphan(
                        pos, strategy, reason="orphan_safety_close"
                    )

        except Exception as e:
            log.debug(f"Orphan check error: {e}")

    def start(self):
        """Start the engine."""
        mode = "PAPER" if self.paper else "LIVE"
        log.info(f"{'='*60}")
        log.info(f"  KRONOS TRADING ENGINE [{mode}]")
        log.info(f"{'='*60}")
        log.info(f"  Capital: ${self.position_mgr.equity:,.2f}")
        log.info(f"  Timeframe: {self.timeframe}")
        log.info(f"  Strategies:")
        for symbol, strategy in self.strategies:
            log.info(f"    {strategy.name} on {symbol}")
        log.info(f"{'='*60}")

        # Send startup notification
        strats = ", ".join(f"{s.name}({sym})" for sym, s in self.strategies)
        self.telegram.send_alert(
            f"Engine Started [{mode}]",
            f"Capital: ${self.position_mgr.equity:,.2f}\n"
            f"Timeframe: {self.timeframe}\n"
            f"Strategies: {strats}",
        )

        # Initialize strategies with historical data
        self._warmup_strategies()

        # Reconcile orphaned positions from journal
        self._reconcile_open_positions()

        # Self-tune: init tables and apply pending recommendations
        try:
            self._init_param_tables()
            self._apply_pending_params()
        except Exception as e:
            log.warning(f"Self-tune startup error (continuing): {e}")

        # Market-intel context (added 2026-05-12). Fail-open: any fetch
        # failure logs "unavailable" and the engine proceeds normally.
        if MARKET_INTEL_ENABLED:
            for line in format_context_log():
                log.info(line)
            self._last_market_intel_log = time.time()
        else:
            self._last_market_intel_log = 0.0
            log.info("[MARKET INTEL] disabled via config")

        # Main loop
        self.running = True
        try:
            self._run_loop()
        except KeyboardInterrupt:
            log.info("Keyboard interrupt received")
        except Exception as e:
            log.error(f"Engine error: {e}", exc_info=True)
            self.telegram.send_error(str(e))
        finally:
            self.stop()

    def stop(self):
        """Graceful shutdown."""
        self.running = False

        # Close all positions
        for pos_id in list(self.position_mgr.positions.keys()):
            pos = self.position_mgr.positions[pos_id]
            price = self.exchange.get_price(pos.symbol)
            if price:
                trade = self.position_mgr.close_position(pos_id, price, "engine_shutdown")
                if trade:
                    self.telegram.send_trade_close({**trade, "reason": "engine_shutdown"})
                    self.journal.log_exit(trade, None, "unknown")
                    self._check_param_revert(trade)

        # Final status
        status = self.position_mgr.get_status()
        self.telegram.send_status(status)

        log.info(f"Engine stopped. Final equity: ${status['equity']:,.2f} "
                 f"({status['total_return_pct']:+.2f}%)")

    def _warmup_strategies(self):
        """Load historical candles to initialize strategy state."""
        log.info("Warming up strategies with historical data...")

        seen_symbols = set()
        for symbol, strategy in self.strategies:
            key = self._strategy_key(symbol, strategy)
            candles = load_recent_candles(symbol, self.timeframe, n_candles=500)

            if candles:
                enrich_candles_batch(candles, symbol, self.tf_ms)

            strategy.on_init()

            # Feed history to strategy (without acting on signals)
            for candle in candles:
                strategy._update_history(candle)
                strategy.on_candle(candle)  # warm up indicators

            self.strategy_histories[key] = candles
            if candles:
                self.last_candle_ts[symbol] = candles[-1].timestamp_ms

            log.info(f"  {strategy.name} on {symbol}: {len(candles)} candles loaded")
            seen_symbols.add(symbol)

    def _run_loop(self):
        """Main trading loop."""
        while self.running:
            try:
                self.cycle_count += 1
                cycle_start = time.time()

                # Periodic market-intel context re-log (every 4h wall-clock)
                if (MARKET_INTEL_ENABLED and self._last_market_intel_log
                        and (cycle_start - self._last_market_intel_log
                             >= MARKET_INTEL_CONTEXT_LOG_INTERVAL_SEC)):
                    for line in format_context_log():
                        log.info(line)
                    self._last_market_intel_log = cycle_start

                # 1. Check for new candles
                new_candles = self._check_new_candles()

                # 2. Process new candles through strategies
                if new_candles:
                    self._process_candles(new_candles)

                # 3. Update positions with current prices
                self._update_positions()

                # 4. Safety check for orphaned positions (every cycle)
                self._check_orphan_positions()

                # 5. Periodic status + self-tune check
                if time.time() - self.last_status_time > self.status_interval:
                    self._send_status()
                    self.last_status_time = time.time()
                    # Check for new parameter recommendations
                    try:
                        self._apply_pending_params()
                    except Exception as e:
                        log.debug(f"Self-tune periodic check error: {e}")

                # 6. Sleep until next check
                # Check more frequently than candle period for price updates
                sleep_time = min(self.tf_seconds / 3, 60)
                elapsed = time.time() - cycle_start

                if elapsed < sleep_time:
                    time.sleep(sleep_time - elapsed)

            except Exception as e:
                log.error(f"Cycle error: {e}", exc_info=True)
                time.sleep(30)

    def _check_new_candles(self) -> dict[str, list[CandleData]]:
        """Check for new candles since last processed."""
        new_candles = {}
        seen = set()

        for symbol, _ in self.strategies:
            if symbol in seen:
                continue
            seen.add(symbol)

            last_ts = self.last_candle_ts.get(symbol, 0)

            # Load candles newer than what we've seen
            db_path = DATA_DIR / "prices.db"
            if not db_path.exists():
                continue

            conn = sqlite3.connect(str(db_path))
            rows = conn.execute(
                """SELECT timestamp_ms, open, high, low, close, volume
                   FROM ohlcv
                   WHERE symbol = ? AND timeframe = ? AND timestamp_ms > ?
                   ORDER BY timestamp_ms ASC""",
                (symbol, self.timeframe, last_ts),
            ).fetchall()
            conn.close()

            if rows:
                candles = []
                for row in rows:
                    c = CandleData(
                        timestamp_ms=row[0],
                        open=row[1], high=row[2], low=row[3],
                        close=row[4], volume=row[5],
                    )
                    enrich_candle_liquidations(c, symbol, self.tf_ms)
                    candles.append(c)

                new_candles[symbol] = candles
                self.last_candle_ts[symbol] = candles[-1].timestamp_ms

                if self.cycle_count % 10 == 0:  # don't spam logs
                    log.info(f"New candles: {symbol} +{len(candles)}")

        return new_candles

    def _process_candles(self, new_candles: dict[str, list[CandleData]]):
        """Process new candles through strategies and generate signals."""
        signals_generated = 0
        signals_blocked = 0

        # Directional bias gate removed 2026-05-20. STRATEGY_BLOCKED_REGIMES_LONG
        # below is the active regime filter — uses fresh per-cycle regime, not
        # a stale daily snapshot.

        for symbol, strategy in self.strategies:
            if symbol not in new_candles:
                continue

            for candle in new_candles[symbol]:
                strategy._update_history(candle)
                signal = strategy.on_candle(candle)

                if signal is None or signal.direction is None:
                    continue

                signals_generated += 1

                # EXIT signals (direction=0) must ALWAYS pass through — never block a close
                if signal.direction == 0:
                    self._handle_signal(symbol, strategy, signal, candle)
                    continue

                # Regime-aware strategy selection (Component 2d)
                try:
                    regime = self._get_regime(strategy)
                    regime_key = f"{strategy.name}_{symbol}"
                    allowed, reason = self._is_strategy_qualified(strategy.name, regime)

                    # Log on regime change only (throttle)
                    if self._last_regime.get(regime_key) != regime:
                        self._last_regime[regime_key] = regime
                        status = "ALLOWED" if allowed else "BLOCKED"
                        log.info(
                            f"Regime selector: {strategy.name} {status} "
                            f"in {regime} -- {reason}"
                        )

                    if not allowed:
                        signals_blocked += 1
                        continue

                    # Strategy-specific directional regime gate. Uses the
                    # fresh `regime` already computed above (no extra fetch).
                    # Currently configured: vwap_mean_reversion LONG entries
                    # blocked in trending_down (audit 2026-05-11).
                    blocked_regimes = STRATEGY_BLOCKED_REGIMES_LONG.get(
                        strategy.name
                    )
                    if (blocked_regimes is not None
                            and signal.direction == 1
                            and regime in blocked_regimes):
                        log.info(
                            f"[GATE] {strategy.name} LONG blocked — "
                            f"regime={regime} in {sorted(blocked_regimes)}"
                        )
                        signals_blocked += 1
                        continue
                except Exception as e:
                    log.debug(f"Regime selector error (allowing trade): {e}")

                self._handle_signal(symbol, strategy, signal, candle)

        # Log when ALL signals in a cycle were blocked
        if signals_generated > 0 and signals_blocked == signals_generated:
            log.info(
                f"Regime selector: no qualified strategies this cycle "
                f"({signals_blocked}/{signals_generated} signals blocked)"
            )

    def _handle_signal(
        self,
        symbol: str,
        strategy: BaseStrategy,
        signal: Signal,
        candle: CandleData,
    ):
        """Process a strategy signal."""
        key = self._strategy_key(symbol, strategy)

        # Check if we have a position from this strategy
        existing_pos = None
        for pos in self.position_mgr.positions.values():
            if pos.strategy == strategy.name and pos.symbol == symbol:
                existing_pos = pos
                break

        if signal.direction == 0:
            # CLOSE signal
            if existing_pos:
                price = self.exchange.get_price(symbol) or candle.close
                trade = self.position_mgr.close_position(
                    existing_pos.id, price, f"signal_close|{signal.tag}"
                )
                if trade:
                    self.telegram.send_trade_close({**trade, "reason": signal.tag})
                    regime = self._get_regime(strategy)
                    self.journal.log_exit(trade, candle, regime)
                    self._check_param_revert(trade)

        elif signal.direction in (1, -1):
            # LONG or SHORT signal
            side = "long" if signal.direction == 1 else "short"

            # Close opposite position first
            if existing_pos and existing_pos.side != side:
                price = self.exchange.get_price(symbol) or candle.close
                trade = self.position_mgr.close_position(
                    existing_pos.id, price, "signal_reverse"
                )
                if trade:
                    self.telegram.send_trade_close({**trade, "reason": "reverse"})
                    regime = self._get_regime(strategy)
                    self.journal.log_exit(trade, candle, regime)
                    self._check_param_revert(trade)
                existing_pos = None

            # Open new position if not already positioned
            if not existing_pos:
                entry_price = self.exchange.get_price(symbol) or candle.close

                # Calculate position size
                notional = self.position_mgr.calculate_position_size(
                    signal_strength=signal.strength,
                )

                # Market-intel soft sizing gate (added 2026-05-12).
                # Bearish macro AND negative ETF flow → scale notional by
                # MARKET_INTEL_SIZE_DOWN_FACTOR (default 0.75 = -25%).
                # All other conditions, or any fetch failure → full size.
                if MARKET_INTEL_ENABLED:
                    macro = fetch_macro_signals()
                    etf = fetch_etf_flows()
                    mult, reason = compute_size_multiplier(
                        macro, etf,
                        bearish_multiplier=MARKET_INTEL_SIZE_DOWN_FACTOR,
                    )
                    if mult < 1.0:
                        log.info(
                            f"[MARKET INTEL GATE] {reason} | "
                            f"${notional:,.2f} → ${notional * mult:,.2f}"
                        )
                        notional = notional * mult

                quantity = notional / entry_price

                # Calculate stop/take profit from signal metadata
                stop_loss = signal.metadata.get("stop_loss") if signal.metadata else None
                take_profit = signal.metadata.get("take_profit") if signal.metadata else None
                trailing_pct = signal.metadata.get("trailing_stop_pct") if signal.metadata else None

                # Execute order
                if side == "long":
                    result = self.exchange.market_buy(symbol, quantity)
                else:
                    result = self.exchange.market_sell(symbol, quantity)

                if result.success:
                    pos = self.position_mgr.open_position(
                        strategy=strategy.name,
                        symbol=symbol,
                        side=side,
                        entry_price=result.fill_price,
                        quantity=result.fill_quantity,
                        stop_loss=stop_loss,
                        take_profit=take_profit,
                        trailing_stop_pct=trailing_pct,
                        tag=signal.tag,
                    )

                    if pos:
                        self.telegram.send_trade_open({
                            "side": side,
                            "symbol": symbol,
                            "strategy": strategy.name,
                            "entry_price": result.fill_price,
                            "notional_usd": result.fill_price * result.fill_quantity,
                            "stop_loss": stop_loss,
                            "take_profit": take_profit,
                            "tag": signal.tag,
                            "mode": "paper" if self.paper else "live",
                        })

                        # Log to trade journal
                        regime = self._get_regime(strategy)
                        self.journal.log_entry(
                            strategy_name=strategy.name,
                            symbol=symbol,
                            side=side,
                            signal=signal,
                            candle=candle,
                            fill_price=result.fill_price,
                            position=pos,
                            regime=regime,
                        )

                    log.info(
                        f"Signal: {strategy.name} -> {side.upper()} {symbol} | "
                        f"Strength: {signal.strength:.2f} | Tag: {signal.tag}"
                    )
                else:
                    log.warning(f"Order failed: {result.error}")

    def _update_positions(self):
        """Update positions with current prices, check stops."""
        if not self.position_mgr.positions:
            return

        prices = self.exchange.get_all_prices()
        if not prices:
            return

        to_close = self.position_mgr.update_prices(prices)
        for pos_id, price, reason in to_close:
            trade = self.position_mgr.close_position(pos_id, price, reason)
            if trade:
                self.telegram.send_trade_close({**trade, "reason": reason})
                log.info(f"Auto-closed {pos_id}: {reason} @ {price:.2f}")
                # Journal: resolve strategy for regime detection
                strat_obj = None
                for sym, s in self.strategies:
                    if s.name == trade.get("strategy") and sym == trade.get("symbol"):
                        strat_obj = s
                        break
                exit_regime = detect_regime(strat_obj._candle_history) if strat_obj else "unknown"
                self.journal.log_exit(trade, None, exit_regime)
                self._check_param_revert(trade)

    def _send_status(self):
        """Send periodic status update."""
        status = self.position_mgr.get_status()
        self.position_mgr.save_equity_snapshot()

        # Log to console
        log.info(
            f"Status | Equity: ${status['equity']:,.2f} "
            f"({status['total_return_pct']:+.2f}%) | "
            f"DD: {status['drawdown_pct']:.2f}% | "
            f"Positions: {status['positions_count']} | "
            f"Daily PnL: ${status['daily_pnl']:+,.2f}"
        )

        # Send to Telegram
        self.telegram.send_status(status)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def show_status():
    """Show current engine status from DB."""
    db_path = DATA_DIR / "execution.db"
    if not db_path.exists():
        print("No execution database found. Engine hasn't run yet.")
        return

    conn = sqlite3.connect(str(db_path))

    # Recent trades
    trades = conn.execute(
        """SELECT strategy, symbol, side, entry_price, exit_price,
                  pnl_usd, pnl_pct, mode,
                  datetime(entry_time, 'unixepoch'), datetime(exit_time, 'unixepoch')
           FROM trades ORDER BY exit_time DESC LIMIT 10"""
    ).fetchall()

    # Summary
    summary = conn.execute(
        """SELECT mode, COUNT(*), SUM(pnl_usd),
                  SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END),
                  AVG(pnl_pct)
           FROM trades GROUP BY mode"""
    ).fetchall()

    # Latest equity
    equity = conn.execute(
        "SELECT equity, daily_pnl, mode FROM equity_snapshots ORDER BY timestamp DESC LIMIT 1"
    ).fetchone()

    conn.close()

    print("=" * 60)
    print("  KRONOS EXECUTION STATUS")
    print("=" * 60)

    if equity:
        print(f"\n💰 Current Equity: ${equity[0]:,.2f}")
        print(f"📅 Daily PnL: ${equity[1]:+,.2f}")
        print(f"📊 Mode: {equity[2].upper()}")

    if summary:
        for mode, count, total_pnl, wins, avg_pct in summary:
            wr = (wins / count * 100) if count > 0 else 0
            print(f"\n📊 {mode.upper()} Summary:")
            print(f"   Trades: {count} | Win Rate: {wr:.1f}%")
            print(f"   Total PnL: ${total_pnl:+,.2f} | Avg: {avg_pct:+.2f}%")

    if trades:
        print(f"\n📋 Recent Trades:")
        print(f"{'Strategy':15s} {'Symbol':16s} {'Side':6s} {'PnL':>10s} {'%':>8s} {'Mode':>6s}")
        print("-" * 65)
        for t in trades:
            pnl_str = f"${t[5]:+,.2f}" if t[5] else "$0.00"
            pct_str = f"{t[6]:+.2f}%" if t[6] else "0.00%"
            print(f"{t[0]:15s} {t[1]:16s} {t[2]:6s} {pnl_str:>10s} {pct_str:>8s} {t[7]:>6s}")
    else:
        print("\nNo trades recorded yet.")


def main():
    parser = argparse.ArgumentParser(description="Kronos Live Trading Engine")
    parser.add_argument("--strategy", type=str, help="Strategy name(s), comma-separated")
    parser.add_argument("--symbol", type=str, default="BTC-USD",
                        help="Trading symbol (default: BTC-USD)")
    parser.add_argument("--timeframe", type=str, default="5m",
                        help="Candle timeframe (default: 5m)")
    parser.add_argument("--capital", type=float, default=1000.0,
                        help="Starting capital (default: 1000)")
    parser.add_argument("--max-dd", type=float, default=15.0,
                        help="Max drawdown %% before circuit breaker (default: 15)")
    parser.add_argument("--max-pos", type=int, default=5,
                        help="Max concurrent positions (default: 5)")
    parser.add_argument("--params", type=str, default=None,
                        help="Strategy params as JSON string")
    parser.add_argument("--status", action="store_true",
                        help="Show current execution status")
    parser.add_argument("--list", action="store_true",
                        help="List available strategies")
    parser.add_argument("--live", action="store_true",
                        help="Enable live trading (default: paper)")

    args = parser.parse_args()

    if args.status:
        show_status()
        return

    if args.list:
        print("Available strategies:")
        for name in list_strategies():
            print(f"  {name}")
        return

    if not args.strategy:
        parser.print_help()
        return

    # Parse strategy params
    params = json.loads(args.params) if args.params else {}

    # Build strategy list
    strategy_pairs = []
    symbols = [s.strip() for s in args.symbol.split(",")]
    strategy_names = [s.strip() for s in args.strategy.split(",")]

    for strat_name in strategy_names:
        for symbol in symbols:
            strategy = load_strategy(strat_name, params)
            strategy_pairs.append((symbol, strategy))

    # Risk config
    risk = RiskConfig(
        max_drawdown_pct=args.max_dd,
        max_positions=args.max_pos,
    )

    # Create and start engine
    engine = LiveEngine(
        strategies=strategy_pairs,
        timeframe=args.timeframe,
        capital=args.capital,
        paper=not args.live,
        risk_config=risk,
    )

    # Handle signals
    def handle_signal(sig, frame):
        log.info("Shutdown signal received...")
        engine.running = False

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    engine.start()


if __name__ == "__main__":
    main()
