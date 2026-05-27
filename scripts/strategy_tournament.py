#!/usr/bin/env python3
"""
Kronos Strategy Tournament Pipeline
====================================
Manages the lifecycle of strategies from candidate → testing → promoted/demoted.

Stages:
    CANDIDATE  - File exists, passes validation and quick backtest
    TESTING    - Running in live engine (paper mode), accumulating trades
    PROMOTED   - Passed live evaluation thresholds
    DEMOTED    - Failed live evaluation, removed from engine
    STANDBY    - Insufficient signals after evaluation period

Usage:
    python3 scripts/strategy_tournament.py --scan          # Scan all strategies, show status
    python3 scripts/strategy_tournament.py --evaluate      # Run Stage 1 backtest on all candidates
    python3 scripts/strategy_tournament.py --review        # Check Stage 2→3 promotion/demotion
    python3 scripts/strategy_tournament.py --evaluate --strategy parabolic_short
"""

import argparse
import importlib.util
import inspect
import json
import logging
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from strategies.templates.base_strategy import BaseStrategy

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("tournament")

# ---------------------------------------------------------------------------
# Configuration — all thresholds in one place
# ---------------------------------------------------------------------------
CONFIG = {
    # Stage 1: Candidate backtest (quick offline check)
    "backtest_symbol": "BTC-USD",
    "backtest_timeframe": "5m",
    "backtest_days": 7,
    "backtest_capital": 10000.0,
    "min_signals_7d": 1,           # Flag as too conservative if 0 signals

    # Stage 2: Testing (live paper evaluation)
    "min_trades_for_review": 20,
    "min_days_for_review": 14,

    # Stage 3: Promotion thresholds
    "promote_win_rate": 40.0,      # %
    "promote_profit_factor": 1.0,
    "promote_min_trades": 20,

    # Stage 3: Demotion thresholds
    "demote_win_rate": 30.0,       # % (below this after min trades)
    "demote_max_dd_pct": 10.0,     # % of allocation

    # Strategy directories to scan
    "strategy_dirs": [
        "strategies/momentum",
        "strategies/reversal",
        "strategies/generated",
    ],
}

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
JOURNAL_DB = DATA_DIR / "trade_journal.db"


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
def init_lifecycle_table():
    """Create strategy_lifecycle table if not exists."""
    conn = sqlite3.connect(str(JOURNAL_DB))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS strategy_lifecycle (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_name TEXT NOT NULL,
            stage TEXT NOT NULL,
            previous_stage TEXT,
            reason TEXT,
            backtest_results TEXT,
            live_stats TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_lifecycle_strategy
        ON strategy_lifecycle(strategy_name)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_lifecycle_stage
        ON strategy_lifecycle(stage)
    """)
    conn.commit()
    conn.close()


def get_current_stage(strategy_name: str) -> Optional[str]:
    """Get the most recent lifecycle stage for a strategy."""
    if not JOURNAL_DB.exists():
        return None
    conn = sqlite3.connect(str(JOURNAL_DB))
    row = conn.execute(
        "SELECT stage FROM strategy_lifecycle WHERE strategy_name = ? ORDER BY id DESC LIMIT 1",
        (strategy_name,),
    ).fetchone()
    conn.close()
    return row[0] if row else None


def log_lifecycle(strategy_name: str, stage: str, previous_stage: str = None,
                  reason: str = "", backtest_results: dict = None,
                  live_stats: dict = None):
    """Record a lifecycle transition."""
    conn = sqlite3.connect(str(JOURNAL_DB))
    conn.execute(
        """INSERT INTO strategy_lifecycle
           (strategy_name, stage, previous_stage, reason, backtest_results, live_stats)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            strategy_name,
            stage,
            previous_stage,
            reason,
            json.dumps(backtest_results) if backtest_results else None,
            json.dumps(live_stats) if live_stats else None,
        ),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Strategy discovery and validation
# ---------------------------------------------------------------------------
def discover_strategies() -> list[dict]:
    """Find all strategy files and their metadata."""
    strategies = []

    for dir_rel in CONFIG["strategy_dirs"]:
        dir_path = PROJECT_ROOT / dir_rel
        if not dir_path.exists():
            continue
        for py_file in sorted(dir_path.glob("*.py")):
            if py_file.name.startswith("_") or py_file.name == "TEMPLATE.py":
                continue
            info = _load_strategy_info(py_file)
            if info:
                strategies.append(info)

    return strategies


def _load_strategy_info(filepath: Path) -> Optional[dict]:
    """Load strategy class from file, return metadata."""
    try:
        spec = importlib.util.spec_from_file_location(filepath.stem, filepath)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as e:
        return {"file": str(filepath), "name": filepath.stem, "error": str(e),
                "valid": False}

    # Find BaseStrategy subclass
    for attr_name in dir(mod):
        obj = getattr(mod, attr_name)
        if (inspect.isclass(obj) and issubclass(obj, BaseStrategy)
                and obj is not BaseStrategy):
            try:
                instance = obj()
                return {
                    "file": str(filepath),
                    "name": instance.name,
                    "class_name": attr_name,
                    "version": getattr(instance, "version", "?"),
                    "params": instance.default_params(),
                    "has_on_candle": hasattr(obj, "on_candle"),
                    "has_get_param": hasattr(instance, "get_param"),
                    "param_ranges": getattr(mod, "PARAM_RANGES", None),
                    "valid": True,
                }
            except Exception as e:
                return {"file": str(filepath), "name": filepath.stem,
                        "error": f"Instantiation failed: {e}", "valid": False}

    return {"file": str(filepath), "name": filepath.stem,
            "error": "No BaseStrategy subclass found", "valid": False}


def validate_strategy(info: dict) -> tuple[bool, list[str]]:
    """Validate a strategy meets the required interface."""
    issues = []

    if not info.get("valid"):
        issues.append(f"Load error: {info.get('error', 'unknown')}")
        return False, issues

    if not info.get("has_on_candle"):
        issues.append("Missing on_candle() method")
    if not info.get("has_get_param"):
        issues.append("Missing get_param() method")
    if not info.get("params"):
        issues.append("default_params() returns empty dict")

    return len(issues) == 0, issues


# ---------------------------------------------------------------------------
# Stage 1: Candidate backtest
# ---------------------------------------------------------------------------
def run_candidate_backtest(info: dict) -> dict:
    """Run quick 7-day backtest on a strategy candidate."""
    from core.backtester import Backtester

    filepath = Path(info["file"])
    class_name = info["class_name"]

    # Load strategy class
    spec = importlib.util.spec_from_file_location(filepath.stem, filepath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    strategy_cls = getattr(mod, class_name)
    strategy = strategy_cls()

    # Compute date range (last N days)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=CONFIG["backtest_days"])

    bt = Backtester(
        symbol=CONFIG["backtest_symbol"],
        timeframe=CONFIG["backtest_timeframe"],
        start_date=start.strftime("%Y-%m-%d"),
        end_date=end.strftime("%Y-%m-%d"),
        initial_capital=CONFIG["backtest_capital"],
        use_liquidation_data=True,
    )

    try:
        report = bt.run(strategy)
    except Exception as e:
        return {"error": str(e), "passed": False}

    result = {
        "symbol": CONFIG["backtest_symbol"],
        "timeframe": CONFIG["backtest_timeframe"],
        "days": CONFIG["backtest_days"],
        "total_trades": report.total_trades,
        "return_pct": round(report.total_return_pct, 2),
        "max_dd_pct": round(report.max_drawdown_pct, 2),
        "win_rate_pct": round(report.win_rate_pct, 1),
        "profit_factor": round(report.profit_factor, 2),
        "sharpe": round(report.sharpe_ratio, 2),
        "avg_hold_hours": round(report.avg_holding_hours, 1),
        "passed": True,
        "too_conservative": report.total_trades < CONFIG["min_signals_7d"],
    }

    return result


# ---------------------------------------------------------------------------
# Stage 2→3: Review live performance
# ---------------------------------------------------------------------------
def get_live_stats(strategy_name: str) -> Optional[dict]:
    """Get live trading stats from trade_journal.db."""
    if not JOURNAL_DB.exists():
        return None

    conn = sqlite3.connect(str(JOURNAL_DB))
    conn.row_factory = sqlite3.Row

    # Closed trades for this strategy
    trades = conn.execute(
        "SELECT * FROM closed_trades WHERE strategy = ? ORDER BY exit_time ASC",
        (strategy_name,),
    ).fetchall()

    if not trades:
        conn.close()
        return {
            "total_trades": 0, "wins": 0, "losses": 0,
            "win_rate_pct": 0, "total_pnl_usd": 0, "profit_factor": 0,
            "max_dd_usd": 0, "days_active": 0,
        }

    total = len(trades)
    wins = sum(1 for t in trades if (t["pnl_usd"] or 0) > 0)
    losses = total - wins
    total_pnl = sum(t["pnl_usd"] or 0 for t in trades)
    win_pnls = [t["pnl_usd"] for t in trades if (t["pnl_usd"] or 0) > 0]
    loss_pnls = [abs(t["pnl_usd"]) for t in trades if (t["pnl_usd"] or 0) <= 0]

    gross_profit = sum(win_pnls) if win_pnls else 0
    gross_loss = sum(loss_pnls) if loss_pnls else 0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    # Duration tracking
    first_trade_time = trades[0]["entry_time"] if trades[0]["entry_time"] else None
    last_trade_time = trades[-1]["exit_time"] if trades[-1]["exit_time"] else None
    days_active = 0
    if first_trade_time and last_trade_time:
        try:
            t0 = datetime.fromisoformat(first_trade_time)
            t1 = datetime.fromisoformat(last_trade_time)
            days_active = (t1 - t0).total_seconds() / 86400
        except Exception:
            pass

    # Max drawdown (cumulative PnL)
    cumulative = 0
    peak = 0
    max_dd = 0
    for t in trades:
        cumulative += t["pnl_usd"] or 0
        peak = max(peak, cumulative)
        dd = peak - cumulative
        max_dd = max(max_dd, dd)

    conn.close()

    return {
        "total_trades": total,
        "wins": wins,
        "losses": losses,
        "win_rate_pct": round(wins / total * 100, 1) if total > 0 else 0,
        "total_pnl_usd": round(total_pnl, 2),
        "profit_factor": round(profit_factor, 2),
        "max_dd_usd": round(max_dd, 2),
        "days_active": round(days_active, 1),
    }


def review_strategy(strategy_name: str, stats: dict) -> tuple[str, str]:
    """
    Decide promotion/demotion based on live stats.
    Returns (new_stage, reason).
    """
    total = stats.get("total_trades", 0)
    wr = stats.get("win_rate_pct", 0)
    pf = stats.get("profit_factor", 0)
    max_dd = stats.get("max_dd_usd", 0)
    days = stats.get("days_active", 0)

    min_trades = CONFIG["min_trades_for_review"]
    min_days = CONFIG["min_days_for_review"]

    # Not enough data yet
    if total < min_trades and days < min_days:
        return "TESTING", f"Still evaluating: {total}/{min_trades} trades, {days:.0f}/{min_days} days"

    # Demotion checks (checked first for safety)
    if total >= min_trades and wr < CONFIG["demote_win_rate"]:
        return "DEMOTED", f"Win rate {wr:.1f}% < {CONFIG['demote_win_rate']}% after {total} trades"

    # Max DD check (relative to per-strategy capital estimate)
    # Assuming equal capital split, estimate allocation
    if max_dd > 0:
        # Use absolute USD threshold since we don't know exact allocation here
        # The deploy script sets per-strategy capital
        dd_pct_estimate = max_dd / (CONFIG["backtest_capital"] / 3) * 100  # rough estimate
        if dd_pct_estimate > CONFIG["demote_max_dd_pct"]:
            return "DEMOTED", f"Max DD ${max_dd:.2f} exceeds {CONFIG['demote_max_dd_pct']}% threshold"

    # Promotion check
    if total >= CONFIG["promote_min_trades"]:
        if wr >= CONFIG["promote_win_rate"] and pf >= CONFIG["promote_profit_factor"]:
            return "PROMOTED", (
                f"WR {wr:.1f}% >= {CONFIG['promote_win_rate']}%, "
                f"PF {pf:.2f} >= {CONFIG['promote_profit_factor']}, "
                f"{total} trades"
            )

    # Standby: enough time but not enough trades
    if days >= min_days and total < min_trades:
        return "STANDBY", f"Only {total} trades in {days:.0f} days — needs parameter loosening"

    return "TESTING", f"In progress: {total} trades, {days:.0f} days"


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
def get_active_strategies() -> list[str]:
    """Read which strategies are currently in the engine service file."""
    svc_path = Path.home() / ".config" / "systemd" / "user" / "kronos-engine.service"
    if not svc_path.exists():
        return []
    content = svc_path.read_text()
    for line in content.splitlines():
        if "--strategy" in line:
            # Parse: --strategy name1,name2,name3
            parts = line.split("--strategy")
            if len(parts) > 1:
                strat_part = parts[1].strip().split()[0]
                return [s.strip() for s in strat_part.split(",") if s.strip()]
    return []


def cmd_scan():
    """Scan all strategies and show their lifecycle status."""
    strategies = discover_strategies()
    active = get_active_strategies()

    print(f"\n{'=' * 80}")
    print(f"  STRATEGY INVENTORY — {len(strategies)} found")
    print(f"{'=' * 80}")

    print(f"\n{'Name':<30} {'Ver':>4} {'Stage':<12} {'Valid':>5} {'Notes'}")
    print("-" * 80)

    for info in strategies:
        name = info["name"]
        version = info.get("version", "?")
        valid = "OK" if info.get("valid") else "FAIL"
        stage = get_current_stage(name) or "—"

        if name in active:
            stage = "TESTING"

        notes = []
        if name in active:
            notes.append("LIVE")
        if info.get("error"):
            notes.append(info["error"][:30])
        if info.get("param_ranges"):
            notes.append("has PARAM_RANGES")

        print(f"{name:<30} {version:>4} {stage:<12} {valid:>5}  {', '.join(notes)}")

    print(f"\n  Active in engine: {', '.join(active) if active else '(none)'}")
    print()


def cmd_evaluate(strategy_filter: str = None):
    """Run Stage 1 backtest on candidate strategies."""
    strategies = discover_strategies()
    active = get_active_strategies()

    if strategy_filter:
        strategies = [s for s in strategies if s["name"] == strategy_filter]
        if not strategies:
            print(f"Strategy '{strategy_filter}' not found.")
            return

    print(f"\n{'=' * 80}")
    print(f"  STAGE 1 EVALUATION — Quick backtest ({CONFIG['backtest_days']}d)")
    print(f"{'=' * 80}")

    results = []

    for info in strategies:
        name = info["name"]
        valid, issues = validate_strategy(info)

        if not valid:
            print(f"\n  {name}: INVALID — {', '.join(issues)}")
            continue

        # Skip strategies already in testing
        if name in active and not strategy_filter:
            print(f"\n  {name}: Already TESTING (live) — skipping")
            continue

        print(f"\n  {name} v{info.get('version', '?')} — backtesting...")
        bt_result = run_candidate_backtest(info)

        if bt_result.get("error"):
            print(f"    ERROR: {bt_result['error']}")
            continue

        # Display results
        r = bt_result
        print(f"    Trades: {r['total_trades']:>4}  |  Return: {r['return_pct']:>+7.2f}%  |  "
              f"DD: {r['max_dd_pct']:>5.2f}%  |  WR: {r['win_rate_pct']:>5.1f}%  |  "
              f"PF: {r['profit_factor']:>5.2f}  |  Sharpe: {r['sharpe']:>5.2f}")
        print(f"    Avg hold: {r['avg_hold_hours']:.1f}h")

        if r["too_conservative"]:
            print(f"    ⚠ TOO CONSERVATIVE: {r['total_trades']} signals in {CONFIG['backtest_days']}d")

        grade = _grade_backtest(r)
        print(f"    Grade: {grade}")

        # Log to lifecycle
        prev_stage = get_current_stage(name)
        if prev_stage != "CANDIDATE":
            log_lifecycle(name, "CANDIDATE", prev_stage,
                          f"Backtest grade: {grade}", bt_result)

        results.append({"name": name, "grade": grade, **r})

    # Summary table
    if results:
        print(f"\n{'─' * 80}")
        print(f"  {'Strategy':<28} {'Trades':>6} {'Return':>8} {'WR':>6} {'PF':>6} {'Grade':>8}")
        print(f"{'─' * 80}")
        for r in sorted(results, key=lambda x: x["return_pct"], reverse=True):
            print(f"  {r['name']:<28} {r['total_trades']:>6} {r['return_pct']:>+7.2f}% "
                  f"{r['win_rate_pct']:>5.1f}% {r['profit_factor']:>5.2f} {r['grade']:>8}")


def _grade_backtest(result: dict) -> str:
    """Grade a backtest result for quick triage."""
    if result.get("error"):
        return "ERROR"
    if result["total_trades"] == 0:
        return "NO_SIGNALS"
    if result["return_pct"] > 0 and result["profit_factor"] >= 1.0 and result["total_trades"] >= 3:
        if result["sharpe"] >= 1.0:
            return "A"
        return "B"
    if result["return_pct"] > 0:
        return "C"
    if result["return_pct"] > -5:
        return "D"
    return "F"


def cmd_review():
    """Review all TESTING strategies for promotion/demotion."""
    active = get_active_strategies()

    if not active:
        print("No strategies currently in TESTING (live engine).")
        return

    print(f"\n{'=' * 80}")
    print(f"  STAGE 2→3 REVIEW — Live performance check")
    print(f"{'=' * 80}")

    for name in active:
        stats = get_live_stats(name)
        if not stats:
            print(f"\n  {name}: No trade data yet")
            continue

        new_stage, reason = review_strategy(name, stats)

        print(f"\n  {name}:")
        print(f"    Trades: {stats['total_trades']} | WR: {stats['win_rate_pct']:.1f}% | "
              f"PF: {stats['profit_factor']:.2f} | PnL: ${stats['total_pnl_usd']:+.2f}")
        print(f"    Max DD: ${stats['max_dd_usd']:.2f} | Days: {stats['days_active']:.0f}")
        print(f"    → {new_stage}: {reason}")

        # Log transition if stage changed
        current = get_current_stage(name) or "TESTING"
        if new_stage != current and new_stage != "TESTING":
            log_lifecycle(name, new_stage, current, reason, live_stats=stats)
            print(f"    [Logged: {current} → {new_stage}]")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Kronos Strategy Tournament Pipeline")
    parser.add_argument("--scan", action="store_true", help="Scan all strategies, show status")
    parser.add_argument("--evaluate", action="store_true", help="Run Stage 1 backtest on candidates")
    parser.add_argument("--review", action="store_true", help="Check Stage 2→3 promotion/demotion")
    parser.add_argument("--strategy", type=str, help="Filter to a specific strategy name")
    args = parser.parse_args()

    init_lifecycle_table()

    if args.scan:
        cmd_scan()
    elif args.evaluate:
        cmd_evaluate(args.strategy)
    elif args.review:
        cmd_review()
    else:
        # Default: scan
        cmd_scan()


if __name__ == "__main__":
    main()
