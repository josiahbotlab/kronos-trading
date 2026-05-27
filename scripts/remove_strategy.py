#!/usr/bin/env python3
"""
Remove a strategy from the live Kronos engine.

Usage:
    python3 scripts/remove_strategy.py parabolic_short
    python3 scripts/remove_strategy.py parabolic_short --reason "poor win rate"
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SVC_PATH = Path.home() / ".config" / "systemd" / "user" / "kronos-engine.service"


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
    import re
    content = SVC_PATH.read_text()
    lines = content.splitlines()
    new_lines = []
    for line in lines:
        if "--strategy" in line:
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
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True, capture_output=True)
    subprocess.run(["systemctl", "--user", "restart", "kronos-engine"], check=True, capture_output=True)
    result = subprocess.run(
        ["systemctl", "--user", "is-active", "kronos-engine"],
        capture_output=True, text=True,
    )
    if result.stdout.strip() == "active":
        print("  Engine restarted successfully.")
    else:
        print(f"  WARNING: Engine status is '{result.stdout.strip()}'")


def log_removal(strategy_name: str, reason: str, live_stats: dict = None):
    """Log to strategy_lifecycle table."""
    try:
        from scripts.strategy_tournament import init_lifecycle_table, log_lifecycle, get_current_stage, get_live_stats
        init_lifecycle_table()
        prev = get_current_stage(strategy_name)
        stats = live_stats or get_live_stats(strategy_name)
        log_lifecycle(strategy_name, "DEMOTED", prev, reason, live_stats=stats)
    except Exception as e:
        print(f"  Warning: Could not log to lifecycle table: {e}")


def main():
    parser = argparse.ArgumentParser(description="Remove a strategy from Kronos engine")
    parser.add_argument("strategy", help="Strategy name to remove")
    parser.add_argument("--reason", type=str, default="Manual removal", help="Reason for removal")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen")
    args = parser.parse_args()

    print(f"\n{'=' * 60}")
    print(f"  REMOVE STRATEGY")
    print(f"{'=' * 60}")

    active = get_active_strategies()

    if args.strategy not in active:
        print(f"\n  '{args.strategy}' is not in the live engine.")
        print(f"  Active strategies: {', '.join(active)}")
        sys.exit(1)

    if len(active) <= 1:
        print(f"\n  Cannot remove the last strategy. Engine needs at least one.")
        sys.exit(1)

    new_active = [s for s in active if s != args.strategy]

    print(f"\n  Removing: {args.strategy}")
    print(f"  Reason:   {args.reason}")
    print(f"  Remaining: {', '.join(new_active)}")
    print(f"  Capital split: {len(new_active)} strategies = {100/len(new_active):.1f}% each")

    if args.dry_run:
        print(f"\n  [DRY RUN] Would update service and restart engine.")
        return

    update_service_strategies(new_active)
    sync_kronos_json(new_active)
    log_removal(args.strategy, args.reason)
    restart_engine()

    print(f"\n  ✓ {args.strategy} removed. Strategy file preserved for future re-evaluation.\n")


if __name__ == "__main__":
    main()
