#!/usr/bin/env python3
"""
Kronos Daily Telegram Summary (Component 2e)
===============================================
Sends a daily summary of trading activity to Telegram.

Queries trade_journal.db for the last 24 hours, computes stats,
and sends a formatted message via the existing TelegramNotifier.

Usage:
    python3 scripts/daily_summary.py          # send summary
    python3 scripts/daily_summary.py --dry-run # print but don't send
"""

import argparse
import json
import logging
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from execution.telegram_notifier import TelegramNotifier

DB_PATH = PROJECT_ROOT / "data" / "trade_journal.db"
CONFIG_PATH = PROJECT_ROOT / "config" / "kronos.json"
SKILL_PATH = PROJECT_ROOT / "skills" / "strategy_performance.md"

# Per-strategy gate-deployment dates. Trades after the date are counted in the
# "GATED" section. Trades before are still in "ALL-TIME" only. Add an entry
# here when a new strategy gets a behavioural change worth tracking separately.
GATE_DEPLOYMENT_DATES = {
    "vwap_mean_reversion": "2026-05-12 00:00:00",
}
GRADUATION_TRADE_TARGET = 30

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("daily_summary")


def load_active_strategies() -> list[str]:
    """Read active strategies from kronos.json engine config."""
    try:
        with open(CONFIG_PATH) as f:
            config = json.load(f)
        return config.get("engine", {}).get("strategies", [])
    except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
        log.warning(f"Could not read strategies from {CONFIG_PATH}: {e}")
        return []


def get_trades_last_24h(conn: sqlite3.Connection) -> list[dict]:
    """Get all closed trades in the last 24 hours."""
    conn.row_factory = sqlite3.Row
    cutoff = time.time() - 86400
    rows = conn.execute(
        "SELECT * FROM closed_trades WHERE exit_time > ? ORDER BY exit_time ASC",
        (cutoff,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_open_positions(conn: sqlite3.Connection) -> list[dict]:
    """Get currently open positions."""
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM open_positions").fetchall()
    return [dict(r) for r in rows]


def get_cumulative_stats(conn: sqlite3.Connection, active_strategies: list[str] = None) -> dict:
    """Get all-time cumulative stats, filtered to active strategies only."""
    conn.row_factory = sqlite3.Row
    if active_strategies:
        placeholders = ",".join("?" for _ in active_strategies)
        row = conn.execute(f"""
            SELECT
                COUNT(*) as total_trades,
                SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) as wins,
                SUM(pnl_usd) as total_pnl,
                AVG(pnl_pct) as avg_pnl_pct
            FROM closed_trades
            WHERE strategy IN ({placeholders})
        """, active_strategies).fetchone()
    else:
        row = conn.execute("""
            SELECT
                COUNT(*) as total_trades,
                SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) as wins,
                SUM(pnl_usd) as total_pnl,
                AVG(pnl_pct) as avg_pnl_pct
            FROM closed_trades
        """).fetchone()
    total = row["total_trades"] or 0
    wins = row["wins"] or 0
    return {
        "total_trades": total,
        "win_rate": wins / total if total > 0 else 0.0,
        "total_pnl": row["total_pnl"] or 0.0,
        "avg_pnl_pct": row["avg_pnl_pct"] or 0.0,
    }


def get_gated_stats(conn: sqlite3.Connection) -> dict[str, dict]:
    """Return per-strategy stats for trades closed after the gate-deployment
    date. Returns {strategy_name: {trades, wins, total_pnl, pf, gate_date_iso}}.
    Only includes strategies in GATE_DEPLOYMENT_DATES.
    """
    conn.row_factory = sqlite3.Row
    out: dict[str, dict] = {}
    for strategy, gate_date_iso in GATE_DEPLOYMENT_DATES.items():
        # exit_time is stored as Unix seconds (REAL). Compare against epoch
        # of the gate-deployment date interpreted as UTC.
        try:
            gate_dt = datetime.strptime(gate_date_iso, "%Y-%m-%d %H:%M:%S")
            gate_dt = gate_dt.replace(tzinfo=timezone.utc)
            gate_epoch = gate_dt.timestamp()
        except ValueError as e:
            log.warning(f"Bad gate date for {strategy}: {e}")
            continue
        row = conn.execute(
            "SELECT COUNT(*) AS trades, "
            "SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) AS wins, "
            "SUM(pnl_usd) AS total_pnl, "
            "SUM(CASE WHEN pnl_usd > 0 THEN pnl_usd ELSE 0 END) AS gross_win, "
            "SUM(CASE WHEN pnl_usd < 0 THEN ABS(pnl_usd) ELSE 0 END) AS gross_loss "
            "FROM closed_trades "
            "WHERE strategy = ? AND exit_time > ?",
            (strategy, gate_epoch),
        ).fetchone()
        trades = row["trades"] or 0
        wins   = row["wins"]   or 0
        gw     = row["gross_win"]  or 0.0
        gl     = row["gross_loss"] or 0.0
        out[strategy] = {
            "trades":    trades,
            "wins":      wins,
            "win_rate":  (wins / trades) if trades > 0 else 0.0,
            "total_pnl": row["total_pnl"] or 0.0,
            "pf":        (gw / gl) if gl > 0 else (float("inf") if gw > 0 else 0.0),
            "gate_date_iso": gate_date_iso,
        }
    return out


def get_per_strategy_alltime(conn: sqlite3.Connection, strategy: str) -> dict:
    """Lifetime trade count + WR + PnL for one strategy (no gate filter)."""
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT COUNT(*) AS trades, "
        "SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) AS wins, "
        "SUM(pnl_usd) AS total_pnl "
        "FROM closed_trades WHERE strategy = ?",
        (strategy,),
    ).fetchone()
    trades = row["trades"] or 0
    wins   = row["wins"]   or 0
    return {
        "trades":    trades,
        "win_rate":  (wins / trades) if trades > 0 else 0.0,
        "total_pnl": row["total_pnl"] or 0.0,
    }


def get_recent_skill_updates(conn: sqlite3.Connection) -> list[dict]:
    """Get skill updates from the last 24 hours."""
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM skill_updates WHERE timestamp > datetime('now', '-1 day') ORDER BY id DESC",
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []


def get_last_regime(conn: sqlite3.Connection) -> str:
    """Get the regime from the most recent trade."""
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT regime_at_exit FROM closed_trades ORDER BY exit_time DESC LIMIT 1"
    ).fetchone()
    if row and row["regime_at_exit"]:
        return row["regime_at_exit"]

    # Try from open positions
    row = conn.execute(
        "SELECT regime_at_entry FROM open_positions ORDER BY entry_time DESC LIMIT 1"
    ).fetchone()
    if row and row["regime_at_entry"]:
        return row["regime_at_entry"]

    return "unknown"


def format_summary(
    trades_24h: list[dict],
    open_positions: list[dict],
    cumulative: dict,
    regime: str,
    skill_updates: list[dict],
    active_strats: list[str],
    gated_stats: dict[str, dict] | None = None,
    per_strat_alltime: dict[str, dict] | None = None,
) -> str:
    """Format the daily summary message."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = []

    lines.append(f"<b>KRONOS Daily Summary</b>")
    lines.append(f"<i>{now}</i>")
    lines.append("")

    # Current regime
    regime_emoji = {
        "trending_up": "\U0001f4c8", "trending_down": "\U0001f4c9",
        "ranging": "\u2194\ufe0f", "volatile": "\u26a1", "unknown": "\u2753",
    }.get(regime, "\u2753")
    lines.append(f"{regime_emoji} <b>Regime:</b> {regime}")
    lines.append("")

    # Today's trades
    if trades_24h:
        total_pnl = sum(t["pnl_usd"] for t in trades_24h)
        wins = sum(1 for t in trades_24h if t["pnl_usd"] > 0)
        wr = wins / len(trades_24h) if trades_24h else 0

        pnl_emoji = "\u2705" if total_pnl >= 0 else "\u274c"
        lines.append(f"<b>Last 24h:</b> {len(trades_24h)} trades")
        lines.append(f"{pnl_emoji} PnL: ${total_pnl:+,.2f} | WR: {wr:.0%}")
        lines.append("")

        # Per-strategy breakdown
        by_strat = {}
        for t in trades_24h:
            s = t["strategy"]
            if s not in by_strat:
                by_strat[s] = {"trades": 0, "pnl": 0.0, "wins": 0}
            by_strat[s]["trades"] += 1
            by_strat[s]["pnl"] += t["pnl_usd"]
            if t["pnl_usd"] > 0:
                by_strat[s]["wins"] += 1

        for strat, data in sorted(by_strat.items()):
            swr = data["wins"] / data["trades"] if data["trades"] > 0 else 0
            emoji = "\U0001f7e2" if data["pnl"] >= 0 else "\U0001f534"
            lines.append(
                f"  {emoji} {strat}: {data['trades']}T "
                f"${data['pnl']:+,.2f} WR={swr:.0%}"
            )
        lines.append("")
    else:
        lines.append("\U0001f634 <b>Quiet day</b> \u2014 no trades closed in last 24h")
        lines.append("")

    # Open positions
    if open_positions:
        lines.append(f"\U0001f4c2 <b>Open positions:</b> {len(open_positions)}")
        for p in open_positions:
            lines.append(f"  \u2022 {p['strategy']} {p['side']} {p['symbol']} @ ${p['entry_price']:,.2f}")
        lines.append("")

    # Active strategies — read from config
    if active_strats:
        lines.append(f"\U0001f916 <b>Strategies:</b> {', '.join(active_strats)}")
    else:
        lines.append("\U0001f916 <b>Strategies:</b> <i>(none configured in kronos.json)</i>")
    lines.append("")

    # Gated performance vs all-time per gated strategy
    if gated_stats:
        for strategy, g in sorted(gated_stats.items()):
            gate_date_short = g["gate_date_iso"][:10]  # YYYY-MM-DD
            pf_str = f"{g['pf']:.2f}" if g['pf'] != float('inf') else "inf"
            progress = (
                f"{g['trades']}/{GRADUATION_TRADE_TARGET} trades"
                if g['trades'] < GRADUATION_TRADE_TARGET
                else f"{g['trades']} trades — graduation candidate"
            )
            lines.append(
                f"\U0001f4ca <b>GATED ({strategy}, since {gate_date_short}):</b>"
            )
            lines.append(
                f"  Trades: {g['trades']} | WR: {g['win_rate']*100:.0f}% | "
                f"PnL: ${g['total_pnl']:+,.2f}"
            )
            lines.append(f"  PF: {pf_str} | Progress: {progress}")

            # All-time slice for the same strategy
            if per_strat_alltime and strategy in per_strat_alltime:
                at = per_strat_alltime[strategy]
                pre_gate = at['trades'] - g['trades']
                lines.append(
                    f"\U0001f4c9 <b>{strategy} ALL-TIME (pre + post gate):</b>"
                )
                lines.append(
                    f"  Trades: {at['trades']} | WR: {at['win_rate']*100:.0f}% | "
                    f"PnL: ${at['total_pnl']:+,.2f}"
                )
                if pre_gate > 0:
                    lines.append(
                        f"  <i>({pre_gate} pre-gate trades included)</i>"
                    )
            lines.append("")

    # Skill updates
    if skill_updates:
        lines.append(f"\U0001f9e0 <b>Skill updates:</b> {len(skill_updates)} in last 24h")
        for su in skill_updates[:3]:
            rules = su.get("rules_generated", 0)
            trades_n = su.get("trades_analyzed", 0)
            lines.append(f"  \u2022 {trades_n} trades analyzed, {rules} rules")
        lines.append("")

    # Cumulative stats
    total = cumulative["total_trades"]
    if total > 0:
        lines.append("<b>All-time:</b>")
        lines.append(
            f"  \U0001f4ca {total} trades | WR: {cumulative['win_rate']:.0%} | "
            f"PnL: ${cumulative['total_pnl']:+,.2f}"
        )
    else:
        lines.append("\U0001f4ca <b>All-time:</b> No trades yet (journal active, awaiting first close)")

    # System health
    lines.append("")
    lines.append("\U0001f49a Engine running | Paper mode")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Kronos Daily Telegram Summary")
    parser.add_argument("--dry-run", action="store_true", help="Print message but don't send")
    args = parser.parse_args()

    if not DB_PATH.exists():
        log.error(f"Trade journal not found at {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")

    active_strats = load_active_strategies()

    trades_24h = get_trades_last_24h(conn)
    open_positions = get_open_positions(conn)
    cumulative = get_cumulative_stats(conn, active_strategies=active_strats)
    regime = get_last_regime(conn)
    skill_updates = get_recent_skill_updates(conn)

    # Per-strategy gated vs all-time blocks (vwap_mean_reversion as of 2026-05-12)
    gated_stats = get_gated_stats(conn)
    per_strat_alltime = {
        strategy: get_per_strategy_alltime(conn, strategy)
        for strategy in gated_stats
    }

    # Sanity check: verify filtered count matches sum of per-strategy counts
    if active_strats:
        conn.row_factory = sqlite3.Row
        total_unfiltered = conn.execute("SELECT COUNT(*) as n FROM closed_trades").fetchone()["n"]
        if total_unfiltered != cumulative["total_trades"]:
            excluded = total_unfiltered - cumulative["total_trades"]
            log.info(
                f"All-time stats filtered to {active_strats}: "
                f"{cumulative['total_trades']} active / {total_unfiltered} total "
                f"({excluded} from inactive strategies excluded)"
            )

    conn.close()

    log.info(f"Trades last 24h: {len(trades_24h)}")
    log.info(f"Open positions: {len(open_positions)}")
    log.info(f"Current regime: {regime}")
    log.info(f"Active strategies: {active_strats}")

    message = format_summary(
        trades_24h, open_positions, cumulative, regime, skill_updates, active_strats,
        gated_stats=gated_stats, per_strat_alltime=per_strat_alltime,
    )

    if args.dry_run:
        print("\n" + "=" * 50)
        print("  DRY RUN — Would send to Telegram:")
        print("=" * 50 + "\n")
        # Strip HTML tags for console readability
        import re
        clean = re.sub(r"<[^>]+>", "", message)
        print(clean)
    else:
        notifier = TelegramNotifier()
        if notifier.enabled:
            notifier.send(message)
            log.info("Daily summary sent to Telegram")
        else:
            log.warning("Telegram not configured, printing to console:")
            print(message)

    print("\nDone.")


if __name__ == "__main__":
    main()
