#!/usr/bin/env python3
"""
Kronos Skill Updater (Components 2c + 2g)
============================================
Reads closed_trades from trade_journal.db, computes performance stats,
discovers patterns, analyzes parameters, and writes skills/strategy_performance.md.

Usage:
    python3 scripts/skill_updater.py                 # normal run (needs >= 10 trades)
    python3 scripts/skill_updater.py --force          # run even with 0 trades
    python3 scripts/skill_updater.py --dry-run        # print skill file, don't write
    python3 scripts/skill_updater.py --threshold 20   # require 20+ trades to run
    python3 scripts/skill_updater.py --force --dry-run # test with 0 trades, no write
"""

import argparse
import importlib
import json
import logging
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "data" / "trade_journal.db"
SKILL_PATH = PROJECT_ROOT / "skills" / "strategy_performance.md"
STRATEGY_DIRS = [
    PROJECT_ROOT / "strategies" / "momentum",
    PROJECT_ROOT / "strategies" / "reversal",
    PROJECT_ROOT / "strategies" / "generated",
]

sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("skill_updater")

# Min trades for parameter recommendations
PARAM_MIN_TRADES = 20
# Max parameter change: 20% from current value
PARAM_MAX_CHANGE_PCT = 0.20
# Minimum floor: no parameter can go below 50% of its original default
PARAM_FLOOR_PCT = 0.50
# Cooldown: need at least this many NEW trades (for the same strategy)
# since the last change to the same parameter before recommending again
PARAM_COOLDOWN_TRADES = 20

# Engine config path (for filtering dead strategies out of the skill file)
CONFIG_PATH = PROJECT_ROOT / "config" / "kronos.json"

# Hard ceilings from 210-trade manual analysis (2026-04-16).
# For exit-tightness parameters, the tuner may TIGHTEN below these but never
# LOOSEN above them. This prevents runaway tuning from reverting the manual
# optima when stale parameter_changes rows inflate the effective baseline.
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


def _enforce_optima_ceiling(strategy: str, parameter: str, value: float) -> float:
    """Clamp value down to the manual-optimum ceiling for (strategy, parameter)."""
    ceiling = PARAM_MANUAL_OPTIMA.get(strategy, {}).get(parameter)
    if ceiling is not None and value > ceiling:
        log.info(
            f"Manual-optimum ceiling: {strategy}.{parameter} "
            f"{value} -> {ceiling} (never loosen past 210-trade optimum)"
        )
        return ceiling
    return value


def _load_active_strategies() -> set[str]:
    """Read active strategy names from engine config.

    Used to filter dead strategies out of the generated skill file so rules
    don't waste processing time / clutter the file for removed strategies.
    Returns empty set if config can't be read (no filtering in that case).
    """
    try:
        cfg = json.loads(CONFIG_PATH.read_text())
        eng = cfg.get("engine", cfg.get("live_engine", {}))
        return set(eng.get("strategies", []))
    except Exception as e:
        log.warning(f"Could not load active strategies from {CONFIG_PATH}: {e}")
        return set()

# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

def ensure_tables(conn: sqlite3.Connection):
    """Create all required tables."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS skill_updates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            trades_analyzed INTEGER NOT NULL,
            strategies_active INTEGER NOT NULL,
            rules_generated INTEGER NOT NULL,
            patterns_found TEXT,
            forced INTEGER DEFAULT 0,
            dry_run INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
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


def log_audit(conn: sqlite3.Connection, trades: int, strategies: int,
              rules: int, patterns: list, forced: bool, dry_run: bool):
    """Write an audit row to skill_updates."""
    conn.execute(
        """INSERT INTO skill_updates
           (timestamp, trades_analyzed, strategies_active, rules_generated,
            patterns_found, forced, dry_run)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            datetime.now(timezone.utc).isoformat(),
            trades, strategies, rules,
            json.dumps(patterns),
            int(forced), int(dry_run),
        ),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_trades(conn: sqlite3.Connection) -> list[dict]:
    """Load all closed trades as dicts."""
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM closed_trades ORDER BY exit_time ASC").fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Stats computation (unchanged from v1)
# ---------------------------------------------------------------------------

def compute_strategy_stats(trades: list[dict]) -> dict:
    by_strat = defaultdict(list)
    for t in trades:
        by_strat[t["strategy"]].append(t)

    result = {}
    for name, strat_trades in sorted(by_strat.items()):
        pnls = [t["pnl_usd"] for t in strat_trades]
        pnl_pcts = [t["pnl_pct"] for t in strat_trades]
        wins = sum(1 for p in pnls if p > 0)
        total = len(pnls)
        durations = [t["duration_seconds"] for t in strat_trades if t["duration_seconds"]]
        slippages_entry = [t["entry_slippage"] for t in strat_trades if t["entry_slippage"] is not None]
        slippages_exit = [t["exit_slippage"] for t in strat_trades if t["exit_slippage"] is not None]

        result[name] = {
            "total_trades": total,
            "win_rate": wins / total if total > 0 else 0.0,
            "total_pnl_usd": sum(pnls),
            "avg_pnl_usd": sum(pnls) / total if total > 0 else 0.0,
            "avg_pnl_pct": sum(pnl_pcts) / total if total > 0 else 0.0,
            "best_trade_pct": max(pnl_pcts) if pnl_pcts else 0.0,
            "worst_trade_pct": min(pnl_pcts) if pnl_pcts else 0.0,
            "avg_duration_min": (sum(durations) / len(durations) / 60) if durations else 0.0,
            "avg_entry_slippage": (sum(slippages_entry) / len(slippages_entry)) if slippages_entry else 0.0,
            "avg_exit_slippage": (sum(slippages_exit) / len(slippages_exit)) if slippages_exit else 0.0,
            "profit_factor": _profit_factor(pnls),
        }
    return result


def compute_regime_matrix(trades: list[dict]) -> dict:
    matrix = defaultdict(lambda: defaultdict(list))
    for t in trades:
        matrix[t["strategy"]][t["regime_at_entry"] or "unknown"].append(t)

    result = {}
    for strat, regimes in sorted(matrix.items()):
        result[strat] = {}
        for regime, rtrades in sorted(regimes.items()):
            pnls = [t["pnl_usd"] for t in rtrades]
            wins = sum(1 for p in pnls if p > 0)
            total = len(pnls)
            result[strat][regime] = {
                "trades": total,
                "win_rate": wins / total if total > 0 else 0.0,
                "avg_pnl_pct": sum(t["pnl_pct"] for t in rtrades) / total if total > 0 else 0.0,
                "total_pnl_usd": sum(pnls),
            }
    return result


def compute_hourly_stats(trades: list[dict]) -> dict:
    by_hour = defaultdict(lambda: defaultdict(list))
    for t in trades:
        if t["entry_time"]:
            hour = datetime.fromtimestamp(t["entry_time"], tz=timezone.utc).hour
            by_hour[t["strategy"]][hour].append(t)

    result = {}
    for strat, hours in sorted(by_hour.items()):
        result[strat] = {}
        for hour in range(24):
            htrades = hours.get(hour, [])
            if not htrades:
                continue
            pnls = [t["pnl_usd"] for t in htrades]
            wins = sum(1 for p in pnls if p > 0)
            total = len(pnls)
            result[strat][hour] = {
                "trades": total,
                "win_rate": wins / total if total > 0 else 0.0,
                "avg_pnl_pct": sum(t["pnl_pct"] for t in htrades) / total if total > 0 else 0.0,
            }
    return result


def compute_dow_stats(trades: list[dict]) -> dict:
    DOW_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    by_dow = defaultdict(lambda: defaultdict(list))
    for t in trades:
        if t["entry_time"]:
            dow = datetime.fromtimestamp(t["entry_time"], tz=timezone.utc).weekday()
            by_dow[t["strategy"]][dow].append(t)

    result = {}
    for strat, days in sorted(by_dow.items()):
        result[strat] = {}
        for dow in range(7):
            dtrades = days.get(dow, [])
            if not dtrades:
                continue
            pnls = [t["pnl_usd"] for t in dtrades]
            wins = sum(1 for p in pnls if p > 0)
            total = len(pnls)
            result[strat][DOW_NAMES[dow]] = {
                "trades": total,
                "win_rate": wins / total if total > 0 else 0.0,
                "avg_pnl_pct": sum(t["pnl_pct"] for t in dtrades) / total if total > 0 else 0.0,
            }
    return result


# ---------------------------------------------------------------------------
# Pattern discovery (unchanged from v1)
# ---------------------------------------------------------------------------

def discover_patterns(trades: list[dict], strategy_stats: dict) -> list[dict]:
    patterns = []
    if not trades:
        return patterns

    by_strat = defaultdict(list)
    for t in trades:
        by_strat[t["strategy"]].append(t)

    for strat, strades in by_strat.items():
        if len(strades) < 3:
            continue

        # 1. Bad regimes
        regime_groups = defaultdict(list)
        for t in strades:
            regime_groups[t["regime_at_entry"] or "unknown"].append(t)
        for regime, rtrades in regime_groups.items():
            if len(rtrades) >= 5:
                wr = sum(1 for t in rtrades if t["pnl_usd"] > 0) / len(rtrades)
                if wr < 0.30:
                    patterns.append({
                        "type": "bad_regime", "strategy": strat, "regime": regime,
                        "win_rate": round(wr, 3), "trades": len(rtrades),
                        "rule": f"AVOID {strat} in {regime} regime (WR={wr:.0%}, n={len(rtrades)})",
                    })

        # 2. Bad hours
        hour_groups = defaultdict(list)
        for t in strades:
            if t["entry_time"]:
                h = datetime.fromtimestamp(t["entry_time"], tz=timezone.utc).hour
                hour_groups[h].append(t)
        for hour, htrades in hour_groups.items():
            if len(htrades) >= 3:
                wr = sum(1 for t in htrades if t["pnl_usd"] > 0) / len(htrades)
                if wr < 0.25:
                    patterns.append({
                        "type": "bad_hour", "strategy": strat, "hour_utc": hour,
                        "win_rate": round(wr, 3), "trades": len(htrades),
                        "rule": f"AVOID {strat} at {hour:02d}:00 UTC (WR={wr:.0%}, n={len(htrades)})",
                    })

        # 3. Bad days
        DOW_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        dow_groups = defaultdict(list)
        for t in strades:
            if t["entry_time"]:
                dow = datetime.fromtimestamp(t["entry_time"], tz=timezone.utc).weekday()
                dow_groups[dow].append(t)
        for dow, dtrades in dow_groups.items():
            if len(dtrades) >= 3:
                wr = sum(1 for t in dtrades if t["pnl_usd"] > 0) / len(dtrades)
                if wr < 0.25:
                    patterns.append({
                        "type": "bad_day", "strategy": strat, "day": DOW_NAMES[dow],
                        "win_rate": round(wr, 3), "trades": len(dtrades),
                        "rule": f"AVOID {strat} on {DOW_NAMES[dow]} (WR={wr:.0%}, n={len(dtrades)})",
                    })

        # 4. High slippage
        slippages = [abs(t["entry_slippage"]) for t in strades if t["entry_slippage"] is not None]
        if slippages:
            avg_slip = sum(slippages) / len(slippages)
            avg_price = sum(t["entry_price"] for t in strades) / len(strades)
            slip_pct = avg_slip / avg_price * 100 if avg_price > 0 else 0
            if slip_pct > 0.1:
                patterns.append({
                    "type": "high_slippage", "strategy": strat,
                    "avg_slippage_pct": round(slip_pct, 4),
                    "rule": f"HIGH SLIPPAGE on {strat}: avg {slip_pct:.3f}% of price",
                })

        # 5. Consecutive losses
        max_streak = 0
        current_streak = 0
        for t in strades:
            if t["pnl_usd"] <= 0:
                current_streak += 1
                max_streak = max(max_streak, current_streak)
            else:
                current_streak = 0
        if max_streak >= 5:
            patterns.append({
                "type": "consecutive_losses", "strategy": strat,
                "max_streak": max_streak,
                "rule": f"WARNING {strat}: max {max_streak} consecutive losses",
            })

        # 6. Edge decay
        n = len(strades)
        if n >= 8:
            split = int(n * 0.75)
            early = strades[:split]
            late = strades[split:]
            wr_early = sum(1 for t in early if t["pnl_usd"] > 0) / len(early)
            wr_late = sum(1 for t in late if t["pnl_usd"] > 0) / len(late)
            if wr_late < wr_early - 0.15 and wr_late < 0.40:
                patterns.append({
                    "type": "edge_decay", "strategy": strat,
                    "wr_early": round(wr_early, 3), "wr_late": round(wr_late, 3),
                    "rule": f"EDGE DECAY on {strat}: WR dropped from {wr_early:.0%} to {wr_late:.0%}",
                })

    return patterns


# ---------------------------------------------------------------------------
# Parameter Analysis (Component 2g)
# ---------------------------------------------------------------------------

def _classify_exit(exit_reason: str) -> str:
    """Classify an exit reason string into a category."""
    reason = (exit_reason or "").lower()
    if "stop_loss" in reason:
        return "stop_loss"
    if "take_profit" in reason:
        return "take_profit"
    if "max_hold" in reason:
        return "max_hold"
    if "trailing" in reason:
        return "trailing_stop"
    if "mean_reversion" in reason:
        return "mean_reversion"
    if "reverse" in reason:
        return "signal_reverse"
    if "shutdown" in reason:
        return "shutdown"
    return "other"


def _load_strategy_defaults(strategy_name: str) -> dict:
    """Load a strategy's default params by importing its module."""
    try:
        from strategies.templates.base_strategy import BaseStrategy
        for subdir in ["momentum", "reversal", "generated"]:
            strat_dir = PROJECT_ROOT / "strategies" / subdir
            if not strat_dir.exists():
                continue
            for py_file in strat_dir.glob("*.py"):
                if py_file.stem.startswith("__"):
                    continue
                module_name = f"strategies.{subdir}.{py_file.stem}"
                try:
                    module = importlib.import_module(module_name)
                    for attr_name in dir(module):
                        attr = getattr(module, attr_name)
                        if (isinstance(attr, type) and issubclass(attr, BaseStrategy)
                                and attr is not BaseStrategy):
                            instance = attr()
                            if instance.name == strategy_name:
                                return instance.default_params()
                except Exception:
                    continue
    except Exception:
        pass
    return {}


def _get_effective_params(strategy_name: str, defaults: dict, conn: sqlite3.Connection) -> dict:
    """Get effective current params = defaults + any applied DB changes.

    Enforces PARAM_MANUAL_OPTIMA ceilings at read time so historic
    parameter_changes rows with loosened values never become the analysis
    baseline. The tuner has caused this drift before (see audit 2026-03-17).
    """
    params = dict(defaults)
    try:
        rows = conn.execute(
            """SELECT parameter, new_value FROM parameter_changes
               WHERE strategy = ? ORDER BY id ASC""",
            (strategy_name,),
        ).fetchall()
        for row in rows:
            params[row[0]] = row[1]
    except sqlite3.OperationalError:
        pass

    # Clamp historic loosened values back to manual optima
    optima = PARAM_MANUAL_OPTIMA.get(strategy_name, {})
    for key, ceiling in optima.items():
        if key in params and params[key] > ceiling:
            log.info(
                f"Effective params clamp: {strategy_name}.{key} "
                f"{params[key]} -> {ceiling} (historic loosening ignored)"
            )
            params[key] = ceiling
    return params


def _clamp_change(current: float, recommended: float, default: float = None,
                  strategy: str = None, parameter: str = None) -> float:
    """Clamp a recommended value to within 20% of current, above 50% of default,
    and at or below the manual-optimum ceiling for (strategy, parameter).
    """
    if abs(current) < 1e-8:
        clamped = recommended
    else:
        lower = current * (1.0 - PARAM_MAX_CHANGE_PCT)
        upper = current * (1.0 + PARAM_MAX_CHANGE_PCT)
        if lower > upper:
            lower, upper = upper, lower
        clamped = max(lower, min(upper, recommended))
    # Enforce absolute floor: never go below 50% of original default
    if default is not None and abs(default) > 1e-8:
        floor = default * PARAM_FLOOR_PCT
        if clamped < floor:
            log.info(f"Floor enforced: {clamped:.2f} -> {floor:.2f} (50% of default {default})")
            clamped = floor
    # Enforce manual-optimum ceiling (never loosen past 210-trade optimum)
    if strategy and parameter:
        clamped = _enforce_optima_ceiling(strategy, parameter, clamped)
    return clamped


def _check_cooldown(strategy: str, parameter: str, conn: sqlite3.Connection, n_strat_trades: int) -> bool:
    """Check if enough new trades have occurred since the last change to this param.

    Returns True if the parameter is in cooldown (should NOT recommend).
    """
    try:
        row = conn.execute(
            """SELECT trades_analyzed FROM parameter_changes
               WHERE strategy = ? AND parameter = ?
               ORDER BY id DESC LIMIT 1""",
            (strategy, parameter),
        ).fetchone()
        if row is None:
            return False  # Never changed, no cooldown
        last_trades = row[0] or 0
        new_trades = n_strat_trades - last_trades
        if new_trades < PARAM_COOLDOWN_TRADES:
            log.info(
                f"Cooldown: {strategy}.{parameter} — only {new_trades} new trades "
                f"since last change (need {PARAM_COOLDOWN_TRADES})"
            )
            return True
        return False
    except sqlite3.OperationalError:
        return False


def analyze_parameters(trades: list[dict], conn: sqlite3.Connection) -> list[dict]:
    """
    Analyze closed trades to generate parameter recommendations.

    Only for strategies with >= PARAM_MIN_TRADES trades.
    Only recommends when expected improvement is >10% WR or >15% better avg PnL.
    """
    recommendations = []
    if not trades:
        return recommendations

    by_strat = defaultdict(list)
    for t in trades:
        by_strat[t["strategy"]].append(t)

    for strat_name, strat_trades in by_strat.items():
        if len(strat_trades) < PARAM_MIN_TRADES:
            continue

        defaults = _load_strategy_defaults(strat_name)
        if not defaults:
            log.info(f"Param analysis: could not load defaults for {strat_name}, skipping")
            continue

        current = _get_effective_params(strat_name, defaults, conn)
        n = len(strat_trades)

        # Classify exits
        exits = defaultdict(list)
        for t in strat_trades:
            cat = _classify_exit(t.get("exit_reason", ""))
            exits[cat].append(t)

        winners = [t for t in strat_trades if t["pnl_usd"] > 0]
        losers = [t for t in strat_trades if t["pnl_usd"] <= 0]
        win_rate = len(winners) / n

        # --- 1. Stop Loss Analysis ---
        if "stop_loss_pct" in current:
            if _check_cooldown(strat_name, "stop_loss_pct", conn, n):
                pass  # In cooldown
            else:
                rec = _analyze_stop_loss(strat_name, strat_trades, current, exits, winners, losers, n, win_rate, defaults)
                if rec:
                    recommendations.append(rec)

        # --- 2. Take Profit Analysis ---
        if "take_profit_pct" in current:
            if _check_cooldown(strat_name, "take_profit_pct", conn, n):
                pass  # In cooldown
            else:
                rec = _analyze_take_profit(strat_name, strat_trades, current, exits, winners, losers, n, win_rate, defaults)
                if rec:
                    recommendations.append(rec)

        # --- 3. Max Hold Analysis ---
        max_hold_key = "max_hold_bars" if "max_hold_bars" in current else "momentum_max_hold" if "momentum_max_hold" in current else None
        if max_hold_key:
            if _check_cooldown(strat_name, max_hold_key, conn, n):
                pass  # In cooldown
            else:
                rec = _analyze_max_hold(strat_name, strat_trades, current, exits, max_hold_key, n, defaults)
                if rec:
                    recommendations.append(rec)

        # --- 4. Signal Strength Analysis ---
        if "entry_strength" in current:
            rec = _analyze_signal_strength(strat_name, strat_trades, current, n)
            if rec:
                recommendations.append(rec)

    return recommendations


def _analyze_stop_loss(strat, trades, params, exits, winners, losers, n, win_rate, defaults=None):
    """Analyze if stop_loss_pct needs adjustment."""
    current_sl = params["stop_loss_pct"]
    default_sl = (defaults or {}).get("stop_loss_pct")
    sl_trades = exits.get("stop_loss", [])
    sl_rate = len(sl_trades) / n
    mh_losers = [t for t in exits.get("max_hold", []) if t["pnl_usd"] <= 0]

    # Case 1: SL hit too often (>40%) — SL is too tight
    if sl_rate > 0.40:
        # Estimate: widening SL by 15% would save ~20% of stopped-out trades
        est_saved = int(len(sl_trades) * 0.20)
        est_wr_boost = est_saved / n
        if est_wr_boost >= 0.10:
            new_sl = _clamp_change(current_sl, current_sl * 1.15, default_sl,
                                   strategy=strat, parameter="stop_loss_pct")
            if abs(new_sl - current_sl) > 0.05:
                return {
                    "strategy": strat, "parameter": "stop_loss_pct",
                    "current_value": current_sl, "recommended_value": round(new_sl, 2),
                    "evidence": f"SL hit {sl_rate:.0%} of trades ({len(sl_trades)}/{n}); widen to reduce false stops",
                    "trades_analyzed": n,
                    "expected_improvement": f"+{est_wr_boost:.0%} WR (est {est_saved} trades saved)",
                }

    # Case 2: SL rarely hit but lots of timeout losers — SL is too wide
    if sl_rate < 0.15 and len(mh_losers) > 0.25 * n:
        avg_mh_loss = abs(sum(t["pnl_pct"] for t in mh_losers) / len(mh_losers)) if mh_losers else 0
        if avg_mh_loss > 0 and avg_mh_loss < current_sl:
            new_sl = _clamp_change(current_sl, max(avg_mh_loss * 1.1, current_sl * 0.85), default_sl,
                                   strategy=strat, parameter="stop_loss_pct")
            est_pnl_save = avg_mh_loss * 0.30
            if abs(new_sl - current_sl) > 0.05 and est_pnl_save > 0.15:
                return {
                    "strategy": strat, "parameter": "stop_loss_pct",
                    "current_value": current_sl, "recommended_value": round(new_sl, 2),
                    "evidence": f"Only {sl_rate:.0%} SL exits but {len(mh_losers)} timeout losers (avg loss {avg_mh_loss:.1f}%)",
                    "trades_analyzed": n,
                    "expected_improvement": f"~{est_pnl_save:.1f}% better avg PnL by cutting losers earlier",
                }

    return None


def _analyze_take_profit(strat, trades, params, exits, winners, losers, n, win_rate, defaults=None):
    """Analyze if take_profit_pct needs adjustment."""
    current_tp = params["take_profit_pct"]
    default_tp = (defaults or {}).get("take_profit_pct")
    tp_trades = exits.get("take_profit", [])
    tp_rate = len(tp_trades) / n if n > 0 else 0

    # If very few TP exits but winners exit via trailing/max_hold with modest gains
    non_tp_winners = [w for w in winners if _classify_exit(w.get("exit_reason", "")) != "take_profit"]
    if tp_rate < 0.10 and len(non_tp_winners) >= 5:
        avg_non_tp_win = sum(t["pnl_pct"] for t in non_tp_winners) / len(non_tp_winners)
        if 0 < avg_non_tp_win < current_tp * 0.6:
            new_tp = _clamp_change(current_tp, avg_non_tp_win * 1.3, default_tp,
                                   strategy=strat, parameter="take_profit_pct")
            if new_tp < current_tp - 0.1:
                est_extra_wins = int(len(losers) * 0.10)
                est_wr_boost = est_extra_wins / n
                if est_wr_boost >= 0.05:
                    return {
                        "strategy": strat, "parameter": "take_profit_pct",
                        "current_value": current_tp, "recommended_value": round(new_tp, 2),
                        "evidence": f"Only {tp_rate:.0%} TP exits; winners avg {avg_non_tp_win:.1f}% (TP at {current_tp}% too far)",
                        "trades_analyzed": n,
                        "expected_improvement": f"Tighter TP catches more winners before reversal",
                    }

    return None


def _analyze_max_hold(strat, trades, params, exits, hold_key, n, defaults=None):
    """Analyze if max_hold_bars needs adjustment."""
    current_mh = params[hold_key]
    default_mh = (defaults or {}).get(hold_key)
    mh_trades = exits.get("max_hold", [])
    mh_rate = len(mh_trades) / n if n > 0 else 0

    if mh_rate < 0.20:
        return None

    # Many max_hold exits AND they're mostly losers
    mh_losers = [t for t in mh_trades if t["pnl_usd"] <= 0]
    mh_loss_rate = len(mh_losers) / len(mh_trades) if mh_trades else 0

    if mh_loss_rate > 0.60 and len(mh_losers) >= 5:
        # Analyze: what's the avg duration of winners vs these timeout losers?
        winners = [t for t in trades if t["pnl_usd"] > 0 and t["duration_seconds"]]
        if winners:
            avg_win_dur = sum(t["duration_seconds"] for t in winners) / len(winners)
            # If winners close much faster, reduce max_hold toward winner duration
            tf_seconds = 300  # 5m default
            avg_win_bars = avg_win_dur / tf_seconds
            if avg_win_bars < current_mh * 0.65:
                new_mh = _clamp_change(current_mh, max(avg_win_bars * 1.3, current_mh * 0.80), default_mh,
                                       strategy=strat, parameter=hold_key)
                new_mh = round(new_mh)
                if new_mh < current_mh:
                    est_pnl_improve = abs(sum(t["pnl_pct"] for t in mh_losers) / len(mh_losers)) * 0.25
                    return {
                        "strategy": strat, "parameter": hold_key,
                        "current_value": current_mh, "recommended_value": new_mh,
                        "evidence": f"{mh_rate:.0%} timeout exits, {mh_loss_rate:.0%} are losers; winners avg {avg_win_bars:.0f} bars vs {current_mh} max",
                        "trades_analyzed": n,
                        "expected_improvement": f"~{est_pnl_improve:.1f}% better avg PnL by cutting timeout losers",
                    }

    return None


def _analyze_signal_strength(strat, trades, params, n):
    """Analyze if entry_strength minimum should change."""
    current_es = params["entry_strength"]

    strengths = [(t["signal_strength"], t["pnl_usd"]) for t in trades
                 if t["signal_strength"] is not None]
    if len(strengths) < PARAM_MIN_TRADES:
        return None

    strengths.sort(key=lambda x: x[0])
    mid = len(strengths) // 2
    low_half = strengths[:mid]
    high_half = strengths[mid:]

    if not low_half or not high_half:
        return None

    wr_low = sum(1 for _, p in low_half if p > 0) / len(low_half)
    wr_high = sum(1 for _, p in high_half if p > 0) / len(high_half)
    median_strength = strengths[mid][0]

    # If low-strength signals have much worse WR, raise the threshold
    wr_diff = wr_high - wr_low
    if wr_diff >= 0.15 and wr_low < 0.40:
        new_es = _clamp_change(current_es, min(median_strength, current_es * 1.15))
        if new_es > current_es + 0.02:
            return {
                "strategy": strat, "parameter": "entry_strength",
                "current_value": current_es, "recommended_value": round(new_es, 2),
                "evidence": f"Low-strength WR={wr_low:.0%} vs high-strength WR={wr_high:.0%} (n={n})",
                "trades_analyzed": n,
                "expected_improvement": f"+{wr_diff:.0%} WR by filtering weak signals",
            }

    return None


def save_recommendations(recs: list[dict], conn: sqlite3.Connection, dry_run: bool):
    """Save new pending recommendations to DB (skip if already pending for same strat+param)."""
    if not recs:
        return

    # Get existing pending recs to avoid duplicates
    try:
        existing = set()
        rows = conn.execute(
            "SELECT strategy, parameter FROM parameter_recommendations WHERE status = 'pending'"
        ).fetchall()
        for r in rows:
            existing.add((r[0], r[1]))
    except sqlite3.OperationalError:
        existing = set()

    for rec in recs:
        key = (rec["strategy"], rec["parameter"])
        if key in existing:
            log.info(f"Param rec already pending: {key[0]}.{key[1]}, skipping")
            continue

        if not dry_run:
            conn.execute(
                """INSERT INTO parameter_recommendations
                   (strategy, parameter, current_value, recommended_value,
                    evidence, trades_analyzed, expected_improvement, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')""",
                (rec["strategy"], rec["parameter"], rec["current_value"],
                 rec["recommended_value"], rec["evidence"],
                 rec["trades_analyzed"], rec["expected_improvement"]),
            )
        log.info(f"Param rec: {rec['strategy']}.{rec['parameter']} "
                 f"{rec['current_value']} -> {rec['recommended_value']}")

    if not dry_run:
        conn.commit()


def get_all_recommendations(conn: sqlite3.Connection) -> list[dict]:
    """Load all parameter recommendations for display in skill file."""
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM parameter_recommendations ORDER BY id DESC LIMIT 20"
        ).fetchall()
        return [dict(r) for r in reversed(rows)]
    except sqlite3.OperationalError:
        return []


# ---------------------------------------------------------------------------
# Skill file generation
# ---------------------------------------------------------------------------

def generate_skill_file(
    trades, strategy_stats, regime_matrix, hourly_stats, dow_stats,
    patterns, param_recs, audit_history,
) -> str:
    """Generate the full markdown skill file."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total_trades = len(trades)

    lines = []
    lines.append("# Kronos Strategy Performance")
    lines.append("")
    lines.append(f"*Auto-generated by skill_updater.py | Last updated: {now}*")
    lines.append(f"*Total closed trades analyzed: {total_trades}*")
    lines.append("")

    # --- Active Strategies ---
    lines.append("## Active Strategies")
    lines.append("")
    if strategy_stats:
        lines.append("| Strategy | Trades | Win Rate | Avg PnL% | Total PnL$ | PF | Best% | Worst% | Avg Dur |")
        lines.append("|----------|--------|----------|----------|------------|-----|-------|--------|---------|")
        for name, s in sorted(strategy_stats.items()):
            lines.append(
                f"| {name} | {s['total_trades']} | {s['win_rate']:.0%} | "
                f"{s['avg_pnl_pct']:+.2f}% | ${s['total_pnl_usd']:+.2f} | "
                f"{s['profit_factor']:.2f} | {s['best_trade_pct']:+.2f}% | "
                f"{s['worst_trade_pct']:+.2f}% | {s['avg_duration_min']:.0f}m |"
            )
    else:
        lines.append("*No trades recorded yet. Strategies running: liq_bb_combo, obv_divergence, parabolic_short*")
    lines.append("")

    # --- Regime Performance Matrix ---
    lines.append("## Regime Performance Matrix")
    lines.append("")
    regimes = ["trending_up", "trending_down", "ranging", "volatile", "unknown"]
    if regime_matrix:
        lines.append("| Strategy | " + " | ".join(regimes) + " |")
        lines.append("|----------|" + "|".join(["------"] * len(regimes)) + "|")
        for strat in sorted(regime_matrix.keys()):
            cells = []
            for r in regimes:
                data = regime_matrix[strat].get(r)
                if data and data["trades"] > 0:
                    cells.append(f"{data['win_rate']:.0%} ({data['trades']})")
                else:
                    cells.append("-")
            lines.append(f"| {strat} | " + " | ".join(cells) + " |")
    else:
        lines.append("*Insufficient data. Need trades across different regimes.*")
    lines.append("")

    # --- Time-of-Day Performance ---
    lines.append("## Time-of-Day Performance (UTC)")
    lines.append("")
    if hourly_stats:
        for strat, hours in sorted(hourly_stats.items()):
            lines.append(f"### {strat}")
            lines.append("| Hour | Trades | Win Rate | Avg PnL% |")
            lines.append("|------|--------|----------|----------|")
            for hour in range(24):
                data = hours.get(hour)
                if data:
                    lines.append(f"| {hour:02d}:00 | {data['trades']} | {data['win_rate']:.0%} | {data['avg_pnl_pct']:+.2f}% |")
            lines.append("")
    else:
        lines.append("*Insufficient data.*")
    lines.append("")

    # --- Day-of-Week Performance ---
    lines.append("## Day-of-Week Performance")
    lines.append("")
    if dow_stats:
        for strat, days in sorted(dow_stats.items()):
            lines.append(f"### {strat}")
            lines.append("| Day | Trades | Win Rate | Avg PnL% |")
            lines.append("|-----|--------|----------|----------|")
            for day in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]:
                data = days.get(day)
                if data:
                    lines.append(f"| {day} | {data['trades']} | {data['win_rate']:.0%} | {data['avg_pnl_pct']:+.2f}% |")
            lines.append("")
    else:
        lines.append("*Insufficient data.*")
    lines.append("")

    # --- Learned Rules ---
    lines.append("## Learned Rules")
    lines.append("")
    if patterns:
        for i, p in enumerate(patterns, 1):
            lines.append(f"{i}. **{p['type'].upper()}**: {p['rule']}")
    else:
        lines.append("*No patterns discovered yet. Need more trade data.*")
    lines.append("")

    # --- Parameter Recommendations (NEW - Component 2g) ---
    lines.append("## Parameter Recommendations")
    lines.append("")
    if param_recs:
        lines.append("| Strategy | Parameter | Current | Recommended | Evidence | Status |")
        lines.append("|----------|-----------|---------|-------------|----------|--------|")
        for r in param_recs:
            lines.append(
                f"| {r['strategy']} | {r['parameter']} | {r['current_value']} | "
                f"{r['recommended_value']} | {r.get('evidence', '')[:60]} | {r['status']} |"
            )
    else:
        lines.append("*No parameter recommendations yet. Need >= 20 trades per strategy.*")
    lines.append("")

    # --- Disabled Strategies ---
    lines.append("## Disabled Strategies")
    lines.append("")
    disabled = []
    for strat, s in strategy_stats.items():
        if s["total_trades"] >= 10 and s["win_rate"] < 0.30 and s["total_pnl_usd"] < 0:
            disabled.append((strat, s))
    if disabled:
        for strat, s in disabled:
            lines.append(f"- **{strat}**: Disabled (WR={s['win_rate']:.0%}, PnL=${s['total_pnl_usd']:+.2f}, n={s['total_trades']})")
    else:
        lines.append("*No strategies disabled. All performing within acceptable bounds.*")
    lines.append("")

    # --- Parameter Change Log ---
    lines.append("## Parameter Change Log")
    lines.append("")
    lines.append("*Auto-populated from parameter_changes table. See audit trail in trade_journal.db.*")
    lines.append("")

    # --- Cumulative Stats ---
    lines.append("## Cumulative Stats")
    lines.append("")
    if trades:
        total_pnl = sum(t["pnl_usd"] for t in trades)
        total_wins = sum(1 for t in trades if t["pnl_usd"] > 0)
        all_pnl_pcts = [t["pnl_pct"] for t in trades]
        lines.append(f"- **Total trades**: {total_trades}")
        lines.append(f"- **Overall win rate**: {total_wins/total_trades:.0%}")
        lines.append(f"- **Total PnL**: ${total_pnl:+.2f}")
        lines.append(f"- **Avg PnL per trade**: ${total_pnl/total_trades:+.2f}")
        lines.append(f"- **Avg PnL %**: {sum(all_pnl_pcts)/len(all_pnl_pcts):+.2f}%")
        lines.append(f"- **Profit factor**: {_profit_factor([t['pnl_usd'] for t in trades]):.2f}")
    else:
        lines.append("*No trades recorded yet.*")
    lines.append("")

    # --- Update History ---
    lines.append("## Update History")
    lines.append("")
    if audit_history:
        lines.append("| Timestamp | Trades | Strategies | Rules | Forced |")
        lines.append("|-----------|--------|------------|-------|--------|")
        for a in audit_history[-10:]:
            lines.append(
                f"| {a['timestamp'][:16]} | {a['trades_analyzed']} | "
                f"{a['strategies_active']} | {a['rules_generated']} | "
                f"{'yes' if a['forced'] else 'no'} |"
            )
    else:
        lines.append("*First update.*")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _profit_factor(pnls: list[float]) -> float:
    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))
    if gross_loss < 1e-8:
        return float(gross_profit) if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def get_audit_history(conn: sqlite3.Connection) -> list[dict]:
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM skill_updates ORDER BY id DESC LIMIT 10").fetchall()
        return [dict(r) for r in reversed(rows)]
    except sqlite3.OperationalError:
        return []


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Kronos Skill Updater")
    parser.add_argument("--force", action="store_true", help="Run even with fewer trades than threshold")
    parser.add_argument("--dry-run", action="store_true", help="Print skill file but don't write it")
    parser.add_argument("--threshold", type=int, default=10, help="Min trades required (default: 10)")
    args = parser.parse_args()

    if not DB_PATH.exists():
        log.error(f"Trade journal not found at {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    ensure_tables(conn)

    trades = load_trades(conn)
    total = len(trades)
    log.info(f"Loaded {total} closed trades from journal")

    if total < args.threshold and not args.force:
        log.warning(f"Only {total} trades (threshold={args.threshold}). Use --force to run anyway.")
        conn.close()
        sys.exit(0)

    # Compute all stats
    strategy_stats = compute_strategy_stats(trades)
    regime_matrix = compute_regime_matrix(trades)
    hourly_stats = compute_hourly_stats(trades)
    dow_stats = compute_dow_stats(trades)
    patterns = discover_patterns(trades, strategy_stats)

    # Parameter analysis (Component 2g)
    param_recs_new = analyze_parameters(trades, conn)
    save_recommendations(param_recs_new, conn, args.dry_run)
    all_param_recs = get_all_recommendations(conn)

    # Filter out dead strategies (not in engine config) so the skill file
    # only contains rules for strategies currently running.
    active = _load_active_strategies()
    if active:
        dropped = set(strategy_stats.keys()) - active
        if dropped:
            log.info(f"Filtering dead strategies from skill file: {sorted(dropped)}")
        strategy_stats = {k: v for k, v in strategy_stats.items() if k in active}
        regime_matrix = {k: v for k, v in regime_matrix.items() if k in active}
        hourly_stats = {k: v for k, v in hourly_stats.items() if k in active}
        dow_stats = {k: v for k, v in dow_stats.items() if k in active}
        patterns = [p for p in patterns if p.get("strategy") in active]
        all_param_recs = [r for r in all_param_recs if r["strategy"] in active]

    audit_history = get_audit_history(conn)

    log.info(f"Strategies: {list(strategy_stats.keys()) or ['(none yet)']}")
    log.info(f"Patterns discovered: {len(patterns)}")
    log.info(f"Parameter recommendations: {len(param_recs_new)} new, {len(all_param_recs)} total")

    # Generate skill file
    skill_content = generate_skill_file(
        trades, strategy_stats, regime_matrix, hourly_stats, dow_stats,
        patterns, all_param_recs, audit_history,
    )

    if args.dry_run:
        print("\n" + "=" * 60)
        print("  DRY RUN — Skill file would be written to:")
        print(f"  {SKILL_PATH}")
        print("=" * 60 + "\n")
        print(skill_content)
    else:
        SKILL_PATH.parent.mkdir(parents=True, exist_ok=True)
        SKILL_PATH.write_text(skill_content)
        log.info(f"Skill file written to {SKILL_PATH}")

    # Audit
    rules_count = len(patterns) + len(param_recs_new)
    strat_count = len(strategy_stats) if strategy_stats else 0
    log_audit(conn, total, strat_count, rules_count,
              [p["type"] for p in patterns] + [f"param:{r['parameter']}" for r in param_recs_new],
              args.force, args.dry_run)
    log.info("Audit entry recorded")

    conn.close()

    if patterns:
        print(f"\nDiscovered {len(patterns)} pattern(s):")
        for p in patterns:
            print(f"  -> {p['rule']}")
    if param_recs_new:
        print(f"\n{len(param_recs_new)} parameter recommendation(s):")
        for r in param_recs_new:
            print(f"  -> {r['strategy']}.{r['parameter']}: {r['current_value']} -> {r['recommended_value']}")
    if not patterns and not param_recs_new:
        print("\nNo patterns or parameter recommendations (need more trade data).")

    print(f"\nDone. {total} trades, {strat_count} strategies, {rules_count} rules+recs.")


if __name__ == "__main__":
    main()
