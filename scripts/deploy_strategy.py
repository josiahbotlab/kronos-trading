#!/usr/bin/env python3
"""
Deploy a strategy to the live Kronos engine.

Validates → backtests → adds to engine → restarts.

Usage:
    python3 scripts/deploy_strategy.py strategies/generated/parabolic_short.py
    python3 scripts/deploy_strategy.py parabolic_short        # name-based lookup
    python3 scripts/deploy_strategy.py parabolic_short --skip-backtest
"""

import argparse
import importlib.util
import inspect
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from strategies.templates.base_strategy import BaseStrategy

PROJECT_ROOT = Path(__file__).parent.parent
SVC_PATH = Path.home() / ".config" / "systemd" / "user" / "kronos-engine.service"
STRATEGY_DIRS = [
    PROJECT_ROOT / "strategies" / "momentum",
    PROJECT_ROOT / "strategies" / "reversal",
    PROJECT_ROOT / "strategies" / "generated",
]


def find_strategy_file(name_or_path: str) -> tuple[Path, str, str]:
    """Find strategy file, return (filepath, class_name, strategy_name)."""
    # Try as file path first
    path = Path(name_or_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / name_or_path

    if path.exists() and path.suffix == ".py":
        return _load_and_identify(path)

    # Try as strategy name — search all dirs
    for d in STRATEGY_DIRS:
        if not d.exists():
            continue
        for f in d.glob("*.py"):
            if f.name.startswith("_"):
                continue
            try:
                info = _load_and_identify(f)
                if info[2] == name_or_path:  # strategy_name match
                    return info
            except Exception:
                continue

    raise FileNotFoundError(f"Strategy '{name_or_path}' not found in any strategy directory")


def _load_and_identify(filepath: Path) -> tuple[Path, str, str]:
    """Load a file and return (path, class_name, strategy_name)."""
    spec = importlib.util.spec_from_file_location(filepath.stem, filepath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    for attr_name in dir(mod):
        obj = getattr(mod, attr_name)
        if inspect.isclass(obj) and issubclass(obj, BaseStrategy) and obj is not BaseStrategy:
            instance = obj()
            return filepath, attr_name, instance.name

    raise ValueError(f"No BaseStrategy subclass in {filepath}")


def get_active_strategies() -> list[str]:
    """Read current strategy list from service file."""
    if not SVC_PATH.exists():
        return []
    content = SVC_PATH.read_text()
    for line in content.splitlines():
        if "--strategy" in line:
            parts = line.split("--strategy")
            if len(parts) > 1:
                strat_part = parts[1].strip().split()[0]
                return [s.strip() for s in strat_part.split(",") if s.strip()]
    return []


def update_service_strategies(strategies: list[str]):
    """Update the --strategy flag in the service file."""
    content = SVC_PATH.read_text()
    lines = content.splitlines()
    new_lines = []
    for line in lines:
        if "--strategy" in line:
            # Replace the strategy list
            import re
            new_strat = ",".join(strategies)
            line = re.sub(r'--strategy\s+\S+', f'--strategy {new_strat}', line)
        new_lines.append(line)
    SVC_PATH.write_text("\n".join(new_lines) + "\n")



def sync_kronos_json(strategies: list[str]):
    """Keep kronos.json engine.strategies in sync with service file."""
    config_path = PROJECT_ROOT / "config" / "kronos.json"
    try:
        with open(config_path) as f:
            cfg = json.load(f)
        if "engine" not in cfg:
            cfg["engine"] = {}
        cfg["engine"]["strategies"] = strategies
        with open(config_path, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        print(f"  Warning: could not update kronos.json: {e}")

def restart_engine():
    """Gracefully restart the engine via systemctl."""
    print("  Restarting engine...")
    subprocess.run(
        ["systemctl", "--user", "daemon-reload"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["systemctl", "--user", "restart", "kronos-engine"],
        check=True, capture_output=True,
    )
    # Verify it's running
    result = subprocess.run(
        ["systemctl", "--user", "is-active", "kronos-engine"],
        capture_output=True, text=True,
    )
    if result.stdout.strip() == "active":
        print("  Engine restarted successfully.")
    else:
        print(f"  WARNING: Engine status is '{result.stdout.strip()}'")


def run_backtest(filepath: Path, class_name: str) -> dict:
    """Run Stage 1 backtest via strategy_tournament."""
    from scripts.strategy_tournament import run_candidate_backtest, _load_strategy_info
    info = _load_strategy_info(filepath)
    if not info or not info.get("valid"):
        return {"error": info.get("error", "Failed to load"), "passed": False}
    return run_candidate_backtest(info)


def log_deployment(strategy_name: str, backtest_results: dict = None):
    """Log to strategy_lifecycle table."""
    try:
        from scripts.strategy_tournament import init_lifecycle_table, log_lifecycle, get_current_stage
        init_lifecycle_table()
        prev = get_current_stage(strategy_name)
        log_lifecycle(
            strategy_name, "TESTING", prev,
            "Deployed to live engine",
            backtest_results=backtest_results,
        )
    except Exception as e:
        print(f"  Warning: Could not log to lifecycle table: {e}")


def main():
    parser = argparse.ArgumentParser(description="Deploy a strategy to Kronos engine")
    parser.add_argument("strategy", help="Strategy file path or name")
    parser.add_argument("--skip-backtest", action="store_true", help="Skip Stage 1 backtest")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen")
    args = parser.parse_args()

    print(f"\n{'=' * 60}")
    print(f"  DEPLOY STRATEGY")
    print(f"{'=' * 60}")

    # 1. Find and validate
    try:
        filepath, class_name, strat_name = find_strategy_file(args.strategy)
    except (FileNotFoundError, ValueError) as e:
        print(f"\n  ERROR: {e}")
        sys.exit(1)

    print(f"\n  Strategy:  {strat_name}")
    print(f"  File:      {filepath}")
    print(f"  Class:     {class_name}")

    # 2. Check if already active
    active = get_active_strategies()
    if strat_name in active:
        print(f"\n  '{strat_name}' is already in the live engine.")
        sys.exit(0)

    # 3. Backtest
    bt_result = None
    if not args.skip_backtest:
        print(f"\n  Running 7-day backtest...")
        bt_result = run_backtest(filepath, class_name)

        if bt_result.get("error"):
            print(f"  Backtest ERROR: {bt_result['error']}")
            print(f"  Use --skip-backtest to deploy anyway.")
            sys.exit(1)

        r = bt_result
        print(f"    Trades: {r['total_trades']:>4}  |  Return: {r['return_pct']:>+7.2f}%  |  "
              f"WR: {r['win_rate_pct']:>5.1f}%  |  PF: {r['profit_factor']:>5.2f}")

        if r["too_conservative"]:
            print(f"\n  WARNING: Only {r['total_trades']} trades in 7 days — may be too conservative.")
    else:
        print(f"\n  Backtest skipped.")

    # 4. Deploy
    new_active = active + [strat_name]
    print(f"\n  Strategies after deploy: {', '.join(new_active)}")
    print(f"  Capital split: {len(new_active)} strategies = {100/len(new_active):.1f}% each")

    if args.dry_run:
        print(f"\n  [DRY RUN] Would update service and restart engine.")
        return

    update_service_strategies(new_active)
    sync_kronos_json(new_active)
    log_deployment(strat_name, bt_result)
    restart_engine()

    print(f"\n  ✓ {strat_name} deployed. Monitoring via trade journal + skill file.")
    print(f"  Run 'python3 scripts/strategy_tournament.py --review' after {bt_result.get('total_trades', '?')} trades.\n")


if __name__ == "__main__":
    main()
