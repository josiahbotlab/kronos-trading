#!/usr/bin/env python3
"""
Moon Dev Transcript Monitor — Automated Weekly Pipeline
=========================================================
Scans @MoonDevOnYT for new videos, extracts strategies via Kimi K2.5,
auto-codes promising ones, backtests locally, and alerts on Grade B+.

Runs on VPS where price data and Moonshot API key live.

Supports local transcripts: if VTT files exist in research/new_transcripts/,
they are converted to text and processed directly (no yt-dlp download needed).

Usage:
    python3 scripts/moondev_monitor.py              # Full run
    python3 scripts/moondev_monitor.py --dry-run     # Skip Telegram + state update
    python3 scripts/moondev_monitor.py --force       # Ignore state, recheck all
"""

import argparse
import importlib.util
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Project setup
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from research.transcript_scanner import (
    CHANNEL_URL,
    get_channel_video_list,
    download_transcript,
    _vtt_to_text,
)
from research.kimi_client import KimiLLMClient
from research.evaluate_extracted import (
    generate_strategy_code,
    sanitize_name,
    class_name,
    is_known_strategy,
    is_backtestable,
    KNOWN_STRATEGIES,
    BACKTESTABLE_CATEGORIES,
)
from execution.telegram_notifier import TelegramNotifier

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
STATE_FILE = Path.home() / ".moondev_monitor_state.json"
TRANSCRIPT_DIR = PROJECT_ROOT / "research" / "cache" / "transcripts" / "monitor"
LOCAL_TRANSCRIPT_DIR = PROJECT_ROOT / "research" / "new_transcripts"
GENERATED_DIR = PROJECT_ROOT / "strategies" / "generated"
COOKIES_PATH = PROJECT_ROOT / "config" / "youtube_cookies.txt"
MAX_VIDEOS = 50
MIN_CONFIDENCE = 0.7
GRADE_B_THRESHOLD = 6  # score >= 6 out of 10

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("moondev_monitor")


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------
def load_state() -> dict:
    """Load processing state from disk."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"Failed to load state: {e}")
    return {"last_checked": None, "processed_video_ids": []}


def save_state(state: dict):
    """Persist processing state."""
    state["last_checked"] = datetime.utcnow().strftime("%Y-%m-%d")
    STATE_FILE.write_text(json.dumps(state, indent=2))
    log.info(f"State saved to {STATE_FILE}")


# ---------------------------------------------------------------------------
# Local transcript discovery
# ---------------------------------------------------------------------------
def scan_local_transcripts() -> dict[str, Path]:
    """Scan LOCAL_TRANSCRIPT_DIR for VTT files.

    Returns:
        dict mapping video_id -> vtt_path
    """
    vtt_map = {}
    if not LOCAL_TRANSCRIPT_DIR.exists():
        return vtt_map

    for vtt in LOCAL_TRANSCRIPT_DIR.glob("*.vtt"):
        # Filename: VIDEO_ID.en.vtt or VIDEO_ID.vtt
        vid = vtt.stem.split(".")[0]
        if vid:
            vtt_map[vid] = vtt

    return vtt_map


def convert_vtt_to_text(vtt_path: Path, video_id: str) -> Path | None:
    """Convert a VTT file to clean text, cache in TRANSCRIPT_DIR."""
    txt_path = TRANSCRIPT_DIR / f"{video_id}.txt"
    if txt_path.exists():
        return txt_path

    try:
        clean_text = _vtt_to_text(vtt_path)
        if not clean_text.strip():
            return None
        TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
        txt_path.write_text(clean_text, encoding="utf-8")
        return txt_path
    except Exception as e:
        log.error(f"VTT conversion error for {video_id}: {e}")
        return None


# ---------------------------------------------------------------------------
# Grading (tournament-style scoring)
# ---------------------------------------------------------------------------
def grade_backtest(results: dict) -> tuple[str, int]:
    """Grade backtest results on A-F scale with numeric score (0-10).

    Scoring:
        +2  total_return > 0
        +1  total_return > 5%
        +1  win_rate > 50%
        +1  profit_factor > 1.0
        +1  profit_factor > 1.5
        +1  sharpe > 1.0
        +1  sharpe > 2.0
        +1  max_drawdown < 10%
        +1  total_trades >= 50

    Grade mapping:
        9-10: A   7-8: B   5-6: C   3-4: D   0-2: F
    """
    score = 0
    ret = results.get("total_return_pct", 0)
    wr = results.get("win_rate_pct", 0)
    pf = results.get("profit_factor", 0)
    sharpe = results.get("sharpe_ratio", 0)
    dd = results.get("max_drawdown_pct", 100)
    trades = results.get("total_trades", 0)

    if ret > 0:
        score += 2
    if ret > 5:
        score += 1
    if wr > 50:
        score += 1
    if pf > 1.0:
        score += 1
    if pf > 1.5:
        score += 1
    if sharpe > 1.0:
        score += 1
    if sharpe > 2.0:
        score += 1
    if dd < 10:
        score += 1
    if trades >= 50:
        score += 1

    if score >= 9:
        grade = "A"
    elif score >= 7:
        grade = "B"
    elif score >= 5:
        grade = "C"
    elif score >= 3:
        grade = "D"
    else:
        grade = "F"

    return grade, score


# ---------------------------------------------------------------------------
# Local backtest (runs directly on VPS where price data lives)
# ---------------------------------------------------------------------------
def run_backtest(strategy_path: Path, strategy_name: str, cls_name: str) -> dict | None:
    """Import generated strategy and run backtest locally."""
    try:
        spec = importlib.util.spec_from_file_location(strategy_name, str(strategy_path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        cls = getattr(mod, cls_name)
    except Exception as e:
        log.error(f"Failed to import {strategy_name}: {e}")
        return None

    try:
        from core.backtester import Backtester
        bt = Backtester(symbol="BTC-USD", timeframe="5m", initial_capital=10000.0, use_liquidation_data=True)
        report = bt.run(cls())
        return {
            "total_return_pct": round(report.total_return_pct, 2),
            "max_drawdown_pct": round(report.max_drawdown_pct, 2),
            "sharpe_ratio": round(report.sharpe_ratio, 2),
            "total_trades": report.total_trades,
            "win_rate_pct": round(report.win_rate_pct, 2),
            "profit_factor": round(report.profit_factor, 2),
        }
    except Exception as e:
        log.error(f"Backtest error for {strategy_name}: {e}")
        return None


# ---------------------------------------------------------------------------
# Telegram messages
# ---------------------------------------------------------------------------
def send_strategy_alert(notifier: TelegramNotifier, video_title: str,
                        strategy: dict, results: dict, grade: str, score: int):
    """Send Telegram alert for a Grade B+ strategy."""
    msg = (
        f"<b>MOON DEV MONITOR</b>\n"
        f"New video: {video_title}\n"
        f"Strategy: {strategy['strategy_name']} ({strategy.get('category', '?')})\n"
        f"Grade: {grade} (score {score}/10)\n"
        f"Return: {results['total_return_pct']:+.2f}% | "
        f"WR: {results['win_rate_pct']:.1f}% | "
        f"PF: {results['profit_factor']:.2f}\n"
        f"Sharpe: {results['sharpe_ratio']:.2f} | "
        f"MaxDD: {results['max_drawdown_pct']:.2f}%\n"
        f"Trades: {results['total_trades']}\n"
        f"Action needed: review for live deployment"
    )
    notifier.send(msg)
    log.info(f"Telegram alert sent for {strategy['strategy_name']} (Grade {grade})")


def send_weekly_summary(notifier: TelegramNotifier, videos_scanned: int,
                        strategies_extracted: int, backtested: int, grade_b_plus: int,
                        transcript_failures: int = 0):
    """Send weekly summary (always sent to confirm script is alive)."""
    action = "Review grade B+ strategies." if grade_b_plus > 0 else "No action needed."
    cookie_warn = ""
    if transcript_failures > 0:
        cookie_warn = f"\nTranscript downloads blocked: {transcript_failures} (refresh cookies)"
    msg = (
        f"<b>MOON DEV MONITOR — Weekly Summary</b>\n"
        f"Videos scanned: {videos_scanned} new\n"
        f"Strategies extracted: {strategies_extracted}\n"
        f"Backtested: {backtested}\n"
        f"Grade B+: {grade_b_plus}\n"
        f"{action}{cookie_warn}"
    )
    notifier.send(msg)
    log.info("Weekly summary sent")


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
def run_pipeline(dry_run: bool = False, force: bool = False):
    """Main pipeline: scan -> extract -> code -> backtest -> alert."""

    # Counters for summary
    videos_scanned = 0
    strategies_extracted = 0
    backtested = 0
    grade_b_plus = 0
    transcript_failures = 0

    notifier = TelegramNotifier()
    if not notifier.enabled:
        log.warning("Telegram not configured — alerts will be skipped")

    # Check for YouTube cookies
    cookies = COOKIES_PATH if COOKIES_PATH.exists() else None
    if cookies:
        log.info(f"YouTube cookies: {cookies}")
    else:
        log.warning(f"No YouTube cookies at {COOKIES_PATH} — transcript downloads may be blocked")

    # 1. Load state
    state = load_state()
    last_checked = state.get("last_checked")
    processed_ids = set(state.get("processed_video_ids", []))

    if force:
        log.info("--force: ignoring state, rechecking all videos")
        last_checked = None
        processed_ids = set()
    else:
        log.info(f"State: last_checked={last_checked}, processed={len(processed_ids)} videos")

    # 2. Discover local transcripts
    local_vtt_map = scan_local_transcripts()
    if local_vtt_map:
        log.info(f"Found {len(local_vtt_map)} local transcripts in {LOCAL_TRANSCRIPT_DIR}")

    # 3. Fetch channel video list for titles (works without cookies on VPS)
    title_map = {}
    log.info(f"Fetching video list from {CHANNEL_URL}")
    try:
        channel_videos = get_channel_video_list(CHANNEL_URL, max_videos=500,
                                                cookies_path=cookies)
        for v in (channel_videos or []):
            title_map[v["video_id"]] = v.get("title", v["video_id"])
        log.info(f"Got titles for {len(title_map)} videos from channel")
    except Exception as e:
        log.warning(f"Channel video list failed: {e}")
        channel_videos = []

    # 4. Build unified video list: local transcripts + channel videos
    all_video_ids = set()

    # Add all local transcript video IDs
    for vid in local_vtt_map:
        all_video_ids.add(vid)

    # Add channel videos (for future download if no local transcript)
    for v in (channel_videos or []):
        all_video_ids.add(v["video_id"])

    # Filter out already-processed
    new_video_ids = [vid for vid in sorted(all_video_ids) if vid not in processed_ids]

    # Apply date filter only to channel videos (local transcripts always process)
    if last_checked:
        date_filtered = []
        cutoff = datetime.strptime(last_checked, "%Y-%m-%d")
        channel_dates = {v["video_id"]: v.get("upload_date") for v in (channel_videos or [])}
        for vid in new_video_ids:
            # Always include local transcripts
            if vid in local_vtt_map:
                date_filtered.append(vid)
                continue
            # For channel-only videos, apply date filter
            upload_date = channel_dates.get(vid)
            if upload_date:
                try:
                    if datetime.strptime(upload_date, "%Y%m%d") > cutoff:
                        date_filtered.append(vid)
                except ValueError:
                    date_filtered.append(vid)
            else:
                date_filtered.append(vid)
        new_video_ids = date_filtered

    log.info(f"{len(new_video_ids)} new videos to process "
             f"({sum(1 for v in new_video_ids if v in local_vtt_map)} with local transcripts)")

    if not new_video_ids:
        if not dry_run:
            save_state(state)
            if notifier.enabled:
                send_weekly_summary(notifier, 0, 0, 0, 0)
        return

    # 5. Init LLM client (uses MOONSHOT_API_KEY from environment)
    try:
        llm = KimiLLMClient()
    except ValueError as e:
        log.error(f"LLM client init failed: {e}")
        return

    # Ensure output dirs exist
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)

    total = len(new_video_ids)

    # 6. Process each video
    for idx, vid in enumerate(new_video_ids, 1):
        title = title_map.get(vid, vid)  # fall back to video ID if no title
        log.info(f"\n{'─' * 60}")
        log.info(f"[{idx}/{total}] Processing: {title} ({vid})")

        videos_scanned += 1

        # a. Get transcript: check local VTT first, then try download
        txt_path = None
        if vid in local_vtt_map:
            txt_path = convert_vtt_to_text(local_vtt_map[vid], vid)
            if txt_path:
                log.info(f"Using local transcript: {local_vtt_map[vid].name}")

        if txt_path is None:
            txt_path = download_transcript(vid, TRANSCRIPT_DIR, cookies_path=cookies)

        if txt_path is None:
            log.info(f"No transcript for {vid}, skipping")
            transcript_failures += 1
            processed_ids.add(vid)
            continue

        transcript_text = txt_path.read_text(encoding="utf-8")
        log.info(f"Transcript: {len(transcript_text)} chars")

        # b. Extract strategies via LLM
        try:
            extracted = llm.extract_strategies(transcript_text, title)
        except Exception as e:
            log.error(f"LLM extraction failed for {vid}: {e}")
            processed_ids.add(vid)
            # Rate limit on errors too
            time.sleep(3)
            continue

        log.info(f"Extracted {len(extracted)} strategy concepts")

        # c. Filter viable strategies
        viable = []
        for s in extracted:
            conf = s.get("confidence", 0)
            cat = s.get("category", "other")
            name = s.get("strategy_name", "")

            if conf < MIN_CONFIDENCE:
                log.info(f"  SKIP (low confidence {conf:.0%}): {name}")
                continue
            if cat not in BACKTESTABLE_CATEGORIES and not is_backtestable(s):
                log.info(f"  SKIP (not backtestable): {name}")
                continue
            if is_known_strategy(name):
                log.info(f"  SKIP (known): {name}")
                continue

            log.info(f"  VIABLE: {name} ({conf:.0%}, {cat})")
            # Attach video_title for code generation
            s["video_title"] = title
            viable.append(s)

        strategies_extracted += len(viable)

        # d. Generate code, backtest locally
        for s in viable:
            try:
                filename, strat_name, code = generate_strategy_code(s)
            except Exception as e:
                log.error(f"Code generation failed for {s['strategy_name']}: {e}")
                continue

            # Write strategy file
            strat_path = GENERATED_DIR / filename
            strat_path.write_text(code)
            log.info(f"Generated: {filename}")

            cls = class_name(strat_name)

            # Run backtest directly (we're on VPS with price data)
            results = run_backtest(strat_path, strat_name, cls)
            if results is None:
                log.error(f"Backtest failed for {strat_name}")
                continue

            backtested += 1
            grade, score = grade_backtest(results)
            log.info(
                f"  {strat_name}: Grade {grade} ({score}/10) | "
                f"Return {results['total_return_pct']:+.2f}% | "
                f"WR {results['win_rate_pct']:.1f}% | "
                f"PF {results['profit_factor']:.2f} | "
                f"Sharpe {results['sharpe_ratio']:.2f}"
            )

            # Alert on Grade B+
            if score >= GRADE_B_THRESHOLD:
                grade_b_plus += 1
                if not dry_run and notifier.enabled:
                    send_strategy_alert(notifier, title, s, results, grade, score)

        # e. Mark video as processed
        processed_ids.add(vid)

        # Rate limit between LLM calls
        time.sleep(2)

    # 7. Summary + state update
    log.info(f"\n{'=' * 60}")
    log.info(f"SUMMARY: scanned={videos_scanned}, extracted={strategies_extracted}, "
             f"backtested={backtested}, grade_b+={grade_b_plus}, "
             f"transcript_failures={transcript_failures}")

    if dry_run:
        log.info("DRY RUN — skipping state update and Telegram summary")
    else:
        state["processed_video_ids"] = sorted(processed_ids)
        save_state(state)
        if notifier.enabled:
            send_weekly_summary(notifier, videos_scanned, strategies_extracted,
                                backtested, grade_b_plus, transcript_failures)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Moon Dev Transcript Monitor — weekly pipeline"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Skip Telegram + state update")
    parser.add_argument("--force", action="store_true",
                        help="Ignore state, recheck all videos")
    args = parser.parse_args()

    log.info("Moon Dev Monitor starting")
    try:
        run_pipeline(dry_run=args.dry_run, force=args.force)
    except KeyboardInterrupt:
        log.info("Interrupted")
    except Exception as e:
        log.error(f"Pipeline error: {e}", exc_info=True)
        # Try to send error alert
        try:
            notifier = TelegramNotifier()
            if notifier.enabled:
                notifier.send(f"<b>MOON DEV MONITOR ERROR</b>\n{e}")
        except Exception:
            pass
        sys.exit(1)

    log.info("Moon Dev Monitor done")


if __name__ == "__main__":
    main()
