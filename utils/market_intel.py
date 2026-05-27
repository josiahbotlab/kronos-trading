"""
ai4trade.ai market-intel snapshots — free, unauthenticated, read-only.

Three endpoints exposed:
  - fetch_macro_signals() : verdict + bullish_count / total_count
  - fetch_etf_flows()     : BTC ETF flow summary + estimated flag
  - fetch_macro_news()    : top N macro headlines with sentiment

Design contract
---------------
- Every fetcher is fail-OPEN: any network/parse error returns ``None``,
  never raises. Callers MUST handle None as "no signal — proceed
  normally". This is delayed snapshot data, not a real-time feed; we use
  it for context, never as a hard gate.
- All responses are cached for ``CACHE_SECONDS = 900`` (15 min) since the
  upstream snapshots don't refresh faster than that anyway.
- Tolerant parsing: the upstream schema may evolve; we look up keys by
  name and accept synonyms where the spec leaves room. Unknown shape →
  None.
- urllib only (no `requests` dependency in the Kronos stack).
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

log = logging.getLogger(__name__)

BASE_URL = "https://ai4trade.ai/api/market-intel"
USER_AGENT = "kronos-market-intel/1.0"
HTTP_TIMEOUT = 8         # short — the engine cycle shouldn't stall on this
CACHE_SECONDS = 900      # 15 minutes

_CACHE: dict = {
    "macro": {"ts": 0.0, "payload": None},
    "etf":   {"ts": 0.0, "payload": None},
    "news":  {"ts": 0.0, "payload": None},
}


# =============================================================================
# Low-level GET
# =============================================================================
def _get_json(path: str, params: dict | None = None) -> Optional[dict | list]:
    """GET ``BASE_URL + path`` with params, parse JSON. Returns None on any
    failure. Logs at DEBUG to avoid noise on a stable but flaky endpoint."""
    url = BASE_URL + path
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError,
            json.JSONDecodeError, TimeoutError, OSError) as e:
        log.debug("market_intel GET %s failed: %s", url, e)
        return None


def _cached(key: str, fetcher) -> Optional[dict]:
    """Wrap a fetcher with the module-level 15-min cache."""
    entry = _CACHE[key]
    now = time.time()
    if entry["payload"] is not None and now - entry["ts"] < CACHE_SECONDS:
        return entry["payload"]
    payload = fetcher()
    # Only cache a successful fetch — keep retrying on None so transient
    # failures self-heal on the next call.
    if payload is not None:
        entry["ts"] = now
        entry["payload"] = payload
    return payload


# =============================================================================
# Public fetchers
# =============================================================================
def fetch_macro_signals() -> Optional[dict]:
    """Return ``{"verdict", "bullish_count", "total_count", "raw"}`` or None.

    Maps the upstream payload to a normalised shape. Verdict normalised to
    lowercase {"bullish", "bearish", "neutral"}; unknown → "neutral"."""
    def _fetch():
        raw = _get_json("/macro-signals")
        if raw is None or not isinstance(raw, dict):
            return None
        # Accept several plausible field locations
        verdict = (
            raw.get("verdict")
            or raw.get("overall_verdict")
            or (raw.get("summary", {}) or {}).get("verdict")
            or "neutral"
        )
        verdict_norm = str(verdict).strip().lower()
        if verdict_norm not in ("bullish", "bearish", "neutral"):
            verdict_norm = "neutral"

        # Counts may be at top level, under "signals" array length, or summary
        bullish_count = (
            raw.get("bullish_count")
            or (raw.get("summary", {}) or {}).get("bullish_count")
        )
        total_count = (
            raw.get("total_count")
            or (raw.get("summary", {}) or {}).get("total_count")
        )
        if bullish_count is None or total_count is None:
            signals = raw.get("signals")
            if isinstance(signals, list):
                total_count = total_count or len(signals)
                if bullish_count is None:
                    bullish_count = sum(
                        1 for s in signals
                        if isinstance(s, dict)
                        and str(s.get("sentiment", "")).lower() == "bullish"
                    )
        try:
            bc = int(bullish_count) if bullish_count is not None else 0
            tc = int(total_count) if total_count is not None else 0
        except (TypeError, ValueError):
            bc, tc = 0, 0
        return {
            "verdict": verdict_norm,
            "bullish_count": bc,
            "total_count": tc,
            "raw": raw,
        }
    return _cached("macro", _fetch)


def fetch_etf_flows() -> Optional[dict]:
    """Return ``{"summary", "net_flow_usd", "is_estimated", "raw"}`` or None.

    `net_flow_usd` is the parsed numeric daily/period net flow if present
    (positive = inflow, negative = outflow). `summary` is a human-readable
    string suitable for direct logging."""
    def _fetch():
        raw = _get_json("/etf-flows")
        if raw is None or not isinstance(raw, dict):
            return None
        # Try several plausible field locations
        net = (
            raw.get("net_flow_usd")
            or raw.get("net_flow")
            or raw.get("daily_net_flow")
            or (raw.get("summary", {}) or {}).get("net_flow_usd")
        )
        try:
            net_num = float(net) if net is not None else None
        except (TypeError, ValueError):
            net_num = None
        is_est = bool(
            raw.get("is_estimated")
            or raw.get("estimated")
            or (raw.get("summary", {}) or {}).get("is_estimated")
        )
        # Prefer an explicit summary string if upstream provides one
        summary = (
            raw.get("summary_text")
            or (isinstance(raw.get("summary"), str) and raw["summary"])
            or None
        )
        if summary is None and net_num is not None:
            direction = "+" if net_num >= 0 else ""
            summary = f"net {direction}${net_num:,.0f}"
            if is_est:
                summary += " (estimated)"
        elif summary is None:
            summary = "no flow data"
        return {
            "summary": summary,
            "net_flow_usd": net_num,
            "is_estimated": is_est,
            "raw": raw,
        }
    return _cached("etf", _fetch)


def fetch_macro_news(limit: int = 3) -> Optional[list[dict]]:
    """Return a list of up to ``limit`` headline dicts or None.

    Each item: ``{"title", "sentiment", "url"}`` — keys may be empty
    strings if the upstream doesn't supply them. List order preserved
    from upstream (assumed most-recent-first)."""
    def _fetch():
        raw = _get_json("/news", {"category": "macro", "limit": limit})
        if raw is None:
            return None
        items = (
            raw if isinstance(raw, list)
            else raw.get("items") if isinstance(raw, dict)
            else None
        )
        if not isinstance(items, list):
            return None
        out = []
        for it in items[:limit]:
            if not isinstance(it, dict):
                continue
            out.append({
                "title": str(it.get("title") or it.get("headline") or ""),
                "sentiment": str(it.get("sentiment")
                                  or it.get("label") or "neutral").lower(),
                "url": str(it.get("url") or ""),
            })
        return out
    return _cached("news", _fetch)


# =============================================================================
# Soft sizing gate
# =============================================================================
def compute_size_multiplier(
    macro: Optional[dict],
    etf: Optional[dict],
    bearish_multiplier: float = 0.75,
) -> tuple[float, str]:
    """Return ``(multiplier, reason)`` for the engine to apply at sizing
    time. Soft gate: only when BOTH macro verdict == bearish AND ETF net
    flow is negative do we scale down. All other conditions → 1.0
    (full size). Fail-open: missing data → 1.0.

    The user spec: ``-25%`` sizing when bearish + negative ETF.
    """
    if macro is None or etf is None:
        return 1.0, "market_intel unavailable — full size"
    if macro.get("verdict") != "bearish":
        return 1.0, f"macro {macro.get('verdict','?')} — full size"
    net = etf.get("net_flow_usd")
    if net is None or net >= 0:
        return 1.0, (
            f"macro bearish but ETF flows {net} ≥ 0 — full size"
        )
    return bearish_multiplier, (
        f"bearish macro + negative ETF flow ${net:,.0f} → "
        f"size×{bearish_multiplier}"
    )


def format_context_log() -> list[str]:
    """Return 3 lines describing the current market-intel context.
    Used by the engine for startup + periodic logging. Each line is
    self-contained; missing data is shown rather than skipped, so the
    log is uniform in structure across cycles."""
    lines: list[str] = []
    macro = fetch_macro_signals()
    if macro:
        lines.append(
            f"[MARKET INTEL] Macro: {macro['verdict']} "
            f"({macro['bullish_count']}/{macro['total_count']} signals bullish)"
        )
    else:
        lines.append("[MARKET INTEL] Macro: unavailable")

    etf = fetch_etf_flows()
    if etf:
        est_tag = " (est)" if etf.get("is_estimated") else ""
        lines.append(f"[MARKET INTEL] BTC ETF flows: {etf['summary']}{est_tag}")
    else:
        lines.append("[MARKET INTEL] BTC ETF flows: unavailable")

    news = fetch_macro_news(limit=3)
    if news:
        top = news[0]
        title = top["title"][:100] if top.get("title") else "(no title)"
        sent = top.get("sentiment", "neutral")
        lines.append(f"[MARKET INTEL] Headlines: [{sent}] {title}")
    else:
        lines.append("[MARKET INTEL] Headlines: unavailable")
    return lines
