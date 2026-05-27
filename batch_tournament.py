#!/usr/bin/env python3
"""
Batch Strategy Tournament
=========================
Filters viable concepts from research.db, generates strategy code,
backtests all on BTC-USD 5m, and produces a graded results table.

Usage:
    python3 batch_tournament.py              # Full pipeline
    python3 batch_tournament.py --filter     # Filter only (show viable counts)
    python3 batch_tournament.py --generate   # Filter + generate code
"""

import argparse
import importlib.util
import json
import logging
import os
import re
import signal
import sqlite3
import sys
import textwrap
import traceback
from dataclasses import dataclass
from pathlib import Path

# Project root
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("tournament")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
RESEARCH_DB = PROJECT_ROOT / "research" / "research.db"
PRICES_DB = PROJECT_ROOT / "data" / "prices.db"
GEN_DIR = PROJECT_ROOT / "strategies" / "generated"
RESULTS_FILE = GEN_DIR / "tournament_results.json"

# Existing generated strategies (skip these)
EXISTING_STRATEGIES = set()

# Categories that are backtestable
BACKTESTABLE_CATS = {"momentum", "reversal", "mean_reversion", "breakout", "scalping"}

# Supported indicators for our BaseStrategy
SUPPORTED_INDICATORS = {
    "sma", "ema", "rsi", "bollinger", "bb", "macd", "adx", "atr",
    "vwap", "obv", "volume", "price action", "moving average",
    "crossover", "overbought", "oversold", "support", "resistance",
    "breakout", "pullback", "momentum", "trend", "mean reversion",
    "stochastic", "trailing stop", "stop loss", "take profit",
    "liquidation", "cascade",
}

# Keywords that make a concept NOT viable for 5m BTC auto-coding
DISQUALIFIERS = {
    "order book", "order flow", "ofi", "level 2", "l2 data",
    "tick data", "hft", "high-frequency", "microsecond", "nanosecond",
    "sentiment data", "social media", "twitter", "reddit", "news",
    "fundamental", "earnings", "p/e ratio", "dividend",
    "options", "greeks", "gamma", "delta hedge",
    "arbitrage", "cross-exchange", "cex-dex", "dex",
    "machine learning", "neural network", "xgboost", "random forest",
    "deep learning", "lstm", "tcn", "transformer", "mlp",
    "prediction market", "polymarket", "kalshi",
    "grid bot", "market making", "bid-ask spread",
    "on-chain", "whale wallet", "smart money tracking",
    "equity", "stock", "spy", "qqq", "futures contract",
    "daily chart only", "weekly chart",
    "manual", "discretionary", "visual pattern", "eyeball",
    "risk management only", "position sizing only", "framework",
    "protocol", "circuit breaker", "tilt protection",
    "paper trading setup", "backtesting framework", "incubation",
}


# ---------------------------------------------------------------------------
# Step 1: Filter viable concepts
# ---------------------------------------------------------------------------
def load_all_strategies():
    """Load all strategies from research.db."""
    conn = sqlite3.connect(str(RESEARCH_DB))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT id, strategy_name, category, confidence, description, parameters
        FROM extracted_strategies
        ORDER BY id
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_existing_generated():
    """Get set of already-generated strategy filenames."""
    existing = set()
    if GEN_DIR.exists():
        for f in GEN_DIR.glob("*.py"):
            if f.name.startswith("__"):
                continue
            existing.add(f.stem)
    return existing


def is_viable(strategy: dict) -> tuple[bool, str]:
    """Check if a strategy is viable for auto-coding on 5m BTC.

    Returns (viable, reason_if_not).
    """
    desc = (strategy.get("description") or "").lower()
    name = (strategy.get("strategy_name") or "").lower()
    category = (strategy.get("category") or "").lower()
    params_str = json.dumps(strategy.get("parameters") or {}).lower()
    combined = f"{name} {desc} {params_str}"

    # Must be a backtestable category
    if category not in BACKTESTABLE_CATS:
        return False, f"non-backtestable category: {category}"

    # Check for disqualifiers
    for dq in DISQUALIFIERS:
        if dq in combined:
            return False, f"disqualifier: {dq}"

    # Must have entry logic keywords
    entry_keywords = [
        "enter", "entry", "buy", "sell", "long", "short", "signal",
        "cross", "above", "below", "break", "bounce", "dip",
        "reversal", "pullback", "trigger", "condition",
    ]
    has_entry = any(kw in combined for kw in entry_keywords)
    if not has_entry:
        return False, "no clear entry logic"

    # Must have exit logic keywords
    exit_keywords = [
        "exit", "close", "stop loss", "take profit", "trailing",
        "stop", "target", "tp", "sl", "profit", "loss",
        "time-based", "hold", "bars",
    ]
    has_exit = any(kw in combined for kw in exit_keywords)
    if not has_exit:
        return False, "no clear exit logic"

    # Must use indicators we support
    has_indicator = any(ind in combined for ind in SUPPORTED_INDICATORS)
    if not has_indicator:
        return False, "no supported indicators"

    # Confidence threshold
    if strategy.get("confidence", 0) < 0.5:
        return False, f"low confidence: {strategy['confidence']}"

    return True, "viable"


def categorize(category: str) -> str:
    """Normalize category name."""
    cat = category.lower().strip()
    mapping = {
        "trend_following": "momentum",
        "trend following": "momentum",
    }
    return mapping.get(cat, cat)


def filter_viable(strategies: list[dict]) -> tuple[list[dict], list[dict]]:
    """Filter strategies into viable and skipped."""
    existing = get_existing_generated()
    viable = []
    skipped = []

    for s in strategies:
        sid = s["id"]
        name_snake = sanitize_name(s["strategy_name"])

        # Check if already generated
        candidate_names = [
            name_snake,
            f"research_{sid}_{name_snake}",
        ]
        already_exists = any(cn in existing for cn in candidate_names)
        if already_exists:
            skipped.append({**s, "skip_reason": "already generated"})
            continue

        ok, reason = is_viable(s)
        if ok:
            viable.append(s)
        else:
            skipped.append({**s, "skip_reason": reason})

    return viable, skipped


# ---------------------------------------------------------------------------
# Step 2: Generate strategy code
# ---------------------------------------------------------------------------
def sanitize_name(name: str) -> str:
    """Convert strategy name to valid Python identifier."""
    clean = re.sub(r"\([^)]*\)", "", name).strip()
    clean = re.sub(r"[^a-zA-Z0-9]+", "_", clean).strip("_").lower()
    return clean[:40]


def class_name(snake: str) -> str:
    return "".join(word.capitalize() for word in snake.split("_"))


def detect_indicators(desc: str) -> dict:
    """Detect which indicators are mentioned in the description."""
    d = desc.lower()
    return {
        "rsi": "rsi" in d or "relative strength" in d or "overbought" in d or "oversold" in d,
        "bb": "bollinger" in d or "bb " in d or "bb_" in d or "bband" in d,
        "sma": "sma" in d or "simple moving average" in d,
        "ema": "ema" in d or "exponential moving average" in d,
        "ma": "moving average" in d and "sma" not in d and "ema" not in d,
        "macd": "macd" in d,
        "adx": "adx" in d or "average directional" in d,
        "atr": "atr" in d or "average true range" in d,
        "vwap": "vwap" in d,
        "obv": "obv" in d or "on-balance volume" in d or "on balance volume" in d,
        "volume": "volume" in d and "obv" not in d,
        "stochastic": "stochastic" in d or "stoch" in d,
        "liq": "liquidation" in d or "cascade" in d or "liq_" in d,
    }


def detect_category_style(desc: str, category: str) -> str:
    """Determine if this is reversal/mean-reversion or momentum/breakout."""
    d = desc.lower()
    if category in ("reversal", "mean_reversion"):
        return "reversal"
    if any(kw in d for kw in ["reversal", "mean reversion", "fade", "overbought short", "oversold long"]):
        return "reversal"
    if any(kw in d for kw in ["breakout", "break above", "break below", "squeeze"]):
        return "breakout"
    return "momentum"


def generate_strategy(strategy: dict) -> tuple[str, str, str]:
    """Generate a complete strategy file.

    Returns (filename, strategy_name, code).
    """
    sid = strategy["id"]
    raw_name = strategy["strategy_name"]
    name_snake = sanitize_name(raw_name)
    full_name = f"research_{sid}_{name_snake}"
    name_cls = class_name(full_name)
    desc = strategy.get("description", "")
    category = categorize(strategy.get("category", "other"))
    confidence = strategy.get("confidence", 0)
    params_raw = json.loads(strategy.get("parameters") or "{}")

    indicators = detect_indicators(desc)
    style = detect_category_style(desc, category)

    # --- Build default params ---
    default_params = {
        "trailing_stop_pct": 1.5,
        "take_profit_pct": 3.0,
        "max_hold_bars": 60,     # 60 x 5m = 5 hours
        "cooldown_bars": 12,     # 12 x 5m = 1 hour
        "entry_strength": 0.8,
        "max_history": 500,
    }

    # Extract numeric params from LLM output
    for key, val in params_raw.items():
        if isinstance(val, (int, float)):
            clean_key = sanitize_name(key)
            if clean_key and len(clean_key) > 1:
                default_params[clean_key] = val

    # --- Build indicator blocks and entry conditions ---
    indicator_lines = []
    entry_conditions = []
    direction_logic = ""

    if indicators["rsi"]:
        default_params["rsi_period"] = 14
        default_params["rsi_ob"] = 70
        default_params["rsi_os"] = 30
        indicator_lines.append("""
        current_rsi = self.rsi(self.get_param("rsi_period"))
        if current_rsi is None:
            return Signal(direction=None)""")

        if style == "reversal":
            entry_conditions.append("(current_rsi > self.get_param('rsi_ob') or current_rsi < self.get_param('rsi_os'))")
        else:
            entry_conditions.append("(40 < current_rsi < 70)")  # momentum: not overbought/oversold

    if indicators["bb"]:
        default_params["bb_period"] = 20
        default_params["bb_std"] = 2.0
        indicator_lines.append("""
        bb = self.bollinger_bands(self.get_param("bb_period"), self.get_param("bb_std"))
        if bb is None:
            return Signal(direction=None)
        bb_upper, bb_mid, bb_lower = bb
        bb_width = (bb_upper - bb_lower) / bb_mid if bb_mid > 0 else 0""")

        if style == "reversal":
            entry_conditions.append("(candle.close > bb_upper or candle.close < bb_lower)")
        elif style == "breakout":
            entry_conditions.append("(candle.close > bb_upper or candle.close < bb_lower)")
        else:
            entry_conditions.append("(candle.close > bb_mid)")

    if indicators["sma"] or indicators["ma"]:
        default_params["sma_fast"] = 10
        default_params["sma_slow"] = 30
        indicator_lines.append("""
        sma_f = self.sma(self.get_param("sma_fast"))
        sma_s = self.sma(self.get_param("sma_slow"))
        if sma_f is None or sma_s is None:
            return Signal(direction=None)""")
        entry_conditions.append("True")  # Direction determined below

    if indicators["ema"]:
        default_params["ema_fast"] = 9
        default_params["ema_slow"] = 21
        indicator_lines.append("""
        ema_f = self.ema(self.get_param("ema_fast"))
        ema_s = self.ema(self.get_param("ema_slow"))
        if ema_f is None or ema_s is None:
            return Signal(direction=None)""")
        entry_conditions.append("True")

    if indicators["macd"]:
        default_params["macd_fast"] = 12
        default_params["macd_slow"] = 26
        default_params["macd_signal"] = 9
        indicator_lines.append("""
        # MACD calculation
        ema_fast_val = self.ema(self.get_param("macd_fast"))
        ema_slow_val = self.ema(self.get_param("macd_slow"))
        if ema_fast_val is None or ema_slow_val is None:
            return Signal(direction=None)
        macd_val = ema_fast_val - ema_slow_val""")
        entry_conditions.append("abs(macd_val) > 0")

    if indicators["adx"]:
        default_params["adx_period"] = 14
        default_params["adx_threshold"] = 25
        indicator_lines.append("""
        # ADX approximation using ATR ratio
        atr_short = self.atr(self.get_param("adx_period"))
        atr_long = self.atr(self.get_param("adx_period") * 2)
        if atr_short is None or atr_long is None:
            return Signal(direction=None)
        adx_proxy = (atr_short / atr_long) * 50 if atr_long > 0 else 0""")
        if style == "breakout" or style == "momentum":
            entry_conditions.append(f"adx_proxy > self.get_param('adx_threshold')")
        else:
            entry_conditions.append(f"adx_proxy < self.get_param('adx_threshold')")

    if indicators["atr"]:
        default_params["atr_period"] = 14
        default_params["atr_mult"] = 1.5
        indicator_lines.append("""
        current_atr = self.atr(self.get_param("atr_period"))
        if current_atr is None:
            return Signal(direction=None)""")

    if indicators["vwap"]:
        default_params["vwap_period"] = 20
        indicator_lines.append("""
        # VWAP approximation
        closes_arr = self.closes(self.get_param("vwap_period"))
        volumes_arr = self.volumes(self.get_param("vwap_period"))
        if len(closes_arr) < self.get_param("vwap_period"):
            return Signal(direction=None)
        vwap_val = float(np.sum(closes_arr * volumes_arr) / np.sum(volumes_arr)) if np.sum(volumes_arr) > 0 else candle.close""")
        if style == "reversal":
            entry_conditions.append("(abs(candle.close - vwap_val) / vwap_val > 0.005)")
        else:
            entry_conditions.append("True")

    if indicators["obv"]:
        default_params["obv_period"] = 20
        indicator_lines.append("""
        # OBV trend
        closes_arr = self.closes(self.get_param("obv_period"))
        volumes_arr = self.volumes(self.get_param("obv_period"))
        if len(closes_arr) < self.get_param("obv_period"):
            return Signal(direction=None)
        obv = 0.0
        obv_values = []
        for i in range(1, len(closes_arr)):
            if closes_arr[i] > closes_arr[i-1]:
                obv += volumes_arr[i]
            elif closes_arr[i] < closes_arr[i-1]:
                obv -= volumes_arr[i]
            obv_values.append(obv)
        obv_sma = np.mean(obv_values[-10:]) if len(obv_values) >= 10 else obv""")
        entry_conditions.append("True")

    if indicators["volume"] and not indicators["obv"]:
        default_params["vol_mult"] = 1.5
        default_params["vol_period"] = 20
        indicator_lines.append("""
        volumes_arr = self.volumes(self.get_param("vol_period"))
        if len(volumes_arr) < self.get_param("vol_period"):
            return Signal(direction=None)
        avg_vol = float(np.mean(volumes_arr[:-1])) if len(volumes_arr) > 1 else 1.0
        vol_ratio = candle.volume / avg_vol if avg_vol > 0 else 0""")
        entry_conditions.append(f"vol_ratio >= self.get_param('vol_mult')")

    if indicators["liq"]:
        default_params["liq_percentile"] = 85
        indicator_lines.append("""
        # Liquidation cascade detection
        liq_values = self.liq_usd(200)
        nonzero = liq_values[liq_values > 0]
        if len(nonzero) < 20:
            cascade_active = False
        else:
            threshold = np.percentile(nonzero, self.get_param("liq_percentile"))
            cascade_active = candle.liquidation_usd >= threshold""")
        entry_conditions.append("cascade_active")

    if indicators["stochastic"]:
        default_params["stoch_period"] = 14
        default_params["stoch_ob"] = 80
        default_params["stoch_os"] = 20
        indicator_lines.append("""
        # Stochastic oscillator
        highs_arr = self.highs(self.get_param("stoch_period"))
        lows_arr = self.lows(self.get_param("stoch_period"))
        if len(highs_arr) < self.get_param("stoch_period"):
            return Signal(direction=None)
        highest = float(np.max(highs_arr))
        lowest = float(np.min(lows_arr))
        stoch_k = ((candle.close - lowest) / (highest - lowest) * 100) if highest > lowest else 50""")
        if style == "reversal":
            entry_conditions.append(f"(stoch_k > self.get_param('stoch_ob') or stoch_k < self.get_param('stoch_os'))")
        else:
            entry_conditions.append(f"(self.get_param('stoch_os') < stoch_k < self.get_param('stoch_ob'))")

    # --- Fallback if no indicators detected ---
    if not indicator_lines:
        default_params["fast_period"] = 10
        default_params["slow_period"] = 30
        indicator_lines.append("""
        sma_f = self.sma(self.get_param("fast_period"))
        sma_s = self.sma(self.get_param("slow_period"))
        if sma_f is None or sma_s is None:
            return Signal(direction=None)""")
        entry_conditions.append("True")

    if not entry_conditions:
        entry_conditions.append("True")

    # --- Direction logic ---
    if indicators["rsi"] and style == "reversal":
        direction_logic = """
            # Reversal direction from RSI extremes
            if current_rsi > self.get_param("rsi_ob"):
                direction = -1  # Short overbought
            elif current_rsi < self.get_param("rsi_os"):
                direction = 1   # Long oversold
            else:
                return Signal(direction=None)"""
    elif indicators["bb"] and style == "reversal":
        direction_logic = """
            # Reversal from BB extremes
            if candle.close > bb_upper:
                direction = -1  # Short above upper band
            elif candle.close < bb_lower:
                direction = 1   # Long below lower band
            else:
                return Signal(direction=None)"""
    elif indicators["bb"] and style == "breakout":
        direction_logic = """
            # Breakout direction from BB
            if candle.close > bb_upper:
                direction = 1   # Bullish breakout
            elif candle.close < bb_lower:
                direction = -1  # Bearish breakdown
            else:
                return Signal(direction=None)"""
    elif (indicators["sma"] or indicators["ma"]) and not indicators["ema"]:
        direction_logic = """
            # Direction from SMA crossover
            direction = 1 if sma_f > sma_s else -1"""
    elif indicators["ema"]:
        direction_logic = """
            # Direction from EMA crossover
            direction = 1 if ema_f > ema_s else -1"""
    elif indicators["macd"]:
        direction_logic = """
            # Direction from MACD
            direction = 1 if macd_val > 0 else -1"""
    elif indicators["obv"]:
        direction_logic = """
            # Direction from OBV trend
            direction = 1 if obv > obv_sma else -1"""
    elif indicators["vwap"]:
        if style == "reversal":
            direction_logic = """
            # Direction from VWAP reversion
            if candle.close > vwap_val * 1.005:
                direction = -1  # Short above VWAP
            elif candle.close < vwap_val * 0.995:
                direction = 1   # Long below VWAP
            else:
                return Signal(direction=None)"""
        else:
            direction_logic = """
            # Direction from VWAP
            direction = 1 if candle.close > vwap_val else -1"""
    elif indicators["liq"]:
        direction_logic = """
            # Direction from liquidation imbalance
            total_liq = candle.liquidation_usd
            if total_liq > 0:
                short_ratio = candle.short_liq_usd / total_liq
                if short_ratio > 0.6:
                    direction = 1   # Shorts rekt = bullish
                elif short_ratio < 0.4:
                    direction = -1  # Longs rekt = bearish
                else:
                    return Signal(direction=None)
            else:
                return Signal(direction=None)"""
    elif indicators["stochastic"] and style == "reversal":
        direction_logic = """
            # Direction from Stochastic extremes
            if stoch_k > self.get_param("stoch_ob"):
                direction = -1
            elif stoch_k < self.get_param("stoch_os"):
                direction = 1
            else:
                return Signal(direction=None)"""
    else:
        direction_logic = """
            # Direction from price action
            closes_recent = self.closes(5)
            if len(closes_recent) >= 5:
                direction = 1 if closes_recent[-1] > closes_recent[-3] else -1
            else:
                direction = 1 if candle.close > candle.open else -1"""

    # --- Build param block ---
    param_lines = []
    for k, v in sorted(default_params.items()):
        param_lines.append(f'            "{k}": {v!r},')
    param_block = "\n".join(param_lines)

    # --- Compose indicator block ---
    indicator_block = "\n".join(indicator_lines)

    # --- Entry condition ---
    entry_condition = " and ".join(entry_conditions)

    # --- Generate code ---
    code = f'''#!/usr/bin/env python3
"""
{raw_name}
{"=" * len(raw_name)}
Research ID: {sid}
Category: {category}
Confidence: {confidence:.0%}

{desc[:500]}

Auto-generated for batch tournament evaluation.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from strategies.templates.base_strategy import BaseStrategy, CandleData, Signal
import numpy as np


class {name_cls}(BaseStrategy):
    name = "{full_name}"
    version = "0.1"

    def default_params(self) -> dict:
        return {{
{param_block}
        }}

    def on_init(self):
        self._in_trade = False
        self._trade_direction = 0
        self._bars_held = 0
        self._peak = 0.0
        self._trough = float("inf")
        self._cooldown = 0
        self._diag_counter = 0

    def on_candle(self, candle: CandleData) -> Signal:
        self._diag_counter += 1

        if self._cooldown > 0:
            self._cooldown -= 1

        # --- IN POSITION: manage exits ---
        if self._in_trade:
            self._bars_held += 1

            if self._trade_direction == 1:
                self._peak = max(self._peak, candle.high)
                stop = self._peak * (1 - self.get_param("trailing_stop_pct") / 100)
                tp = self._peak if candle.high >= candle.close * (1 + self.get_param("take_profit_pct") / 100) else 0
                if candle.low <= stop:
                    return self._exit("trailing_stop")
            else:
                self._trough = min(self._trough, candle.low)
                stop = self._trough * (1 + self.get_param("trailing_stop_pct") / 100)
                tp = self._trough if candle.low <= candle.close * (1 - self.get_param("take_profit_pct") / 100) else 0
                if candle.high >= stop:
                    return self._exit("trailing_stop")

            if self._bars_held >= self.get_param("max_hold_bars"):
                return self._exit("max_hold")

            return Signal(direction=None)

        # --- NO POSITION: check for entry ---
        if self._cooldown > 0:
            return Signal(direction=None)

        if len(self._candle_history) < self.get_param("max_history") // 2:
            return Signal(direction=None)
{indicator_block}

        # Entry condition
        if {entry_condition}:
{direction_logic}

            self._in_trade = True
            self._trade_direction = direction
            self._bars_held = 0
            self._peak = candle.high
            self._trough = candle.low

            tag = "{full_name}_bull" if direction == 1 else "{full_name}_bear"
            return Signal(
                direction=direction,
                strength=self.get_param("entry_strength"),
                tag=tag,
            )

        return Signal(direction=None)

    def _exit(self, reason: str) -> Signal:
        self._in_trade = False
        self._trade_direction = 0
        self._cooldown = self.get_param("cooldown_bars")
        return Signal(direction=0, tag=f"exit_{{reason}}")

    def on_trade(self, pnl: float, pnl_pct: float):
        self._in_trade = False
        self._trade_direction = 0
'''

    filename = f"{full_name}.py"
    return filename, full_name, code


# ---------------------------------------------------------------------------
# Step 3: Backtest
# ---------------------------------------------------------------------------
def backtest_strategy(filepath: Path, strategy_name: str) -> dict:
    """Run a single strategy through backtesting."""
    from strategies.templates.base_strategy import BaseStrategy
    from core.backtester import Backtester

    result = {
        "name": strategy_name,
        "file": str(filepath.name),
        "status": "error",
    }

    try:
        # Import the module
        spec = importlib.util.spec_from_file_location(strategy_name, filepath)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # Find the strategy class
        strategy_class = None
        for attr_name in dir(mod):
            attr = getattr(mod, attr_name)
            if (isinstance(attr, type)
                    and issubclass(attr, BaseStrategy)
                    and attr is not BaseStrategy):
                strategy_class = attr
                break

        if not strategy_class:
            result["status"] = "NO_CLASS"
            return result

        # Run backtest on BTC-USD 5m
        bt = Backtester(
            symbol="BTC-USD",
            timeframe="5m",
            initial_capital=10000.0,
            use_liquidation_data=True,
        )

        strategy = strategy_class()
        report = bt.run(strategy)

        if report.total_trades == 0:
            result["status"] = "NO_SIGNALS"
            result["trades"] = 0
            return result

        result.update({
            "status": "ok",
            "trades": report.total_trades,
            "return_pct": round(report.total_return_pct, 2),
            "max_dd_pct": round(report.max_drawdown_pct, 2),
            "sharpe": round(report.sharpe_ratio, 2),
            "win_rate": round(report.win_rate_pct, 1),
            "profit_factor": round(report.profit_factor, 2),
            "avg_trade_pct": round(report.avg_trade_pct, 3),
            "best_trade_pct": round(report.best_trade_pct, 2),
            "worst_trade_pct": round(report.worst_trade_pct, 2),
            "avg_holding_hours": round(report.avg_holding_hours, 1),
            "winning_trades": report.winning_trades,
            "losing_trades": report.losing_trades,
        })

        return result

    except Exception as e:
        result["status"] = "ERROR"
        result["error"] = str(e)[:200]
        return result


def grade_strategy(result: dict) -> str:
    """Assign A/B/C/D/F grade based on metrics."""
    if result.get("status") != "ok":
        return "F"

    trades = result.get("trades", 0)
    ret = result.get("return_pct", 0)
    wr = result.get("win_rate", 0)
    pf = result.get("profit_factor", 0)
    sharpe = result.get("sharpe", 0)
    dd = result.get("max_dd_pct", 100)

    if trades < 5:
        return "F"

    score = 0

    # Return
    if ret > 20: score += 3
    elif ret > 10: score += 2
    elif ret > 0: score += 1

    # Win rate
    if wr > 55: score += 2
    elif wr > 45: score += 1

    # Profit factor
    if pf > 2.0: score += 3
    elif pf > 1.5: score += 2
    elif pf > 1.0: score += 1

    # Sharpe
    if sharpe > 2.0: score += 2
    elif sharpe > 1.0: score += 1

    # Drawdown penalty
    if dd > 30: score -= 2
    elif dd > 20: score -= 1

    # Trade count bonus (enough data)
    if trades > 50: score += 1

    if score >= 8: return "A"
    if score >= 6: return "B"
    if score >= 4: return "C"
    if score >= 2: return "D"
    return "F"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Batch Strategy Tournament")
    parser.add_argument("--filter", action="store_true", help="Filter only, show viable counts")
    parser.add_argument("--generate", action="store_true", help="Filter + generate code")
    args = parser.parse_args()

    # ─── Step 1: Filter ───
    print("\n" + "=" * 70)
    print("  STEP 1: FILTER VIABLE CONCEPTS")
    print("=" * 70)

    strategies = load_all_strategies()
    print(f"Total strategies in research.db: {len(strategies)}")

    viable, skipped = filter_viable(strategies)
    print(f"Viable for auto-coding: {len(viable)}")
    print(f"Skipped: {len(skipped)}")

    # Category breakdown
    cat_counts = {}
    for s in viable:
        cat = categorize(s.get("category", "other"))
        cat_counts[cat] = cat_counts.get(cat, 0) + 1

    print("\nViable by category:")
    for cat, count in sorted(cat_counts.items(), key=lambda x: -x[1]):
        print(f"  {cat:20s}: {count}")

    # Skip reason breakdown
    skip_reasons = {}
    for s in skipped:
        reason = s.get("skip_reason", "unknown")
        # Normalize
        if reason.startswith("disqualifier:"):
            reason_key = "disqualifier"
        else:
            reason_key = reason
        skip_reasons[reason_key] = skip_reasons.get(reason_key, 0) + 1

    print("\nSkip reasons:")
    for reason, count in sorted(skip_reasons.items(), key=lambda x: -x[1]):
        print(f"  {reason:30s}: {count}")

    if args.filter:
        # Show viable list
        print("\n--- Viable strategies ---")
        for s in viable:
            print(f"  [{s['id']:3d}] [{s['confidence']:.0%}] {s['strategy_name'][:50]:50s} ({categorize(s.get('category',''))})")
        return

    # ─── Step 2: Generate ───
    print("\n" + "=" * 70)
    print("  STEP 2: BATCH CODE GENERATION")
    print("=" * 70)

    GEN_DIR.mkdir(parents=True, exist_ok=True)
    init_file = GEN_DIR / "__init__.py"
    if not init_file.exists():
        init_file.write_text("# Auto-generated strategies\n")

    generated = []
    gen_errors = []
    for s in viable:
        try:
            filename, name, code = generate_strategy(s)
            filepath = GEN_DIR / filename
            filepath.write_text(code)
            generated.append({
                "filepath": filepath,
                "name": name,
                "strategy": s,
            })
        except Exception as e:
            gen_errors.append({"strategy": s, "error": str(e)})
            log.error(f"Failed to generate {s['strategy_name']}: {e}")

    print(f"Generated: {len(generated)} strategy files")
    if gen_errors:
        print(f"Generation errors: {len(gen_errors)}")

    if args.generate:
        return

    # ─── Step 3: Backtest all ───
    print("\n" + "=" * 70)
    print("  STEP 3: TOURNAMENT EVALUATION")
    print("=" * 70)

    # Collect ALL research_* strategy files (freshly generated + already existing)
    all_research_files = sorted(GEN_DIR.glob("research_*.py"))
    print(f"Found {len(all_research_files)} research_* strategy files to evaluate")

    # Build a mapping from filename to strategy info (research_id, category)
    # Parse research ID from filename: research_{id}_{name}.py
    def parse_research_file(filepath):
        stem = filepath.stem  # e.g. research_22_md_momentum
        parts = stem.split("_", 2)  # ['research', '22', 'md_momentum']
        if len(parts) >= 2:
            try:
                return int(parts[1]), parts[2] if len(parts) > 2 else ""
            except ValueError:
                pass
        return None, stem

    # Build strategy info lookup from DB
    strat_lookup = {}
    for s in strategies:
        strat_lookup[s["id"]] = s

    results = []
    total = len(all_research_files)
    for i, filepath in enumerate(all_research_files, 1):
        name = filepath.stem
        sid, _ = parse_research_file(filepath)
        strat_info = strat_lookup.get(sid, {})
        cat = categorize(strat_info.get("category", "unknown"))

        print(f"\n[{i}/{total}] Testing: {name}")
        result = backtest_strategy(filepath, name)
        result["research_id"] = sid
        result["category"] = cat
        result["grade"] = grade_strategy(result)

        status = result.get("status", "error")
        if status == "ok":
            print(f"  Return: {result['return_pct']:+.2f}% | "
                  f"Trades: {result['trades']} | "
                  f"WR: {result['win_rate']:.1f}% | "
                  f"PF: {result['profit_factor']:.2f} | "
                  f"Sharpe: {result['sharpe']:.2f} | "
                  f"Grade: {result['grade']}")
        else:
            print(f"  Status: {status}" + (f" - {result.get('error','')[:80]}" if result.get('error') else ""))

        results.append(result)

    # Save raw results
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nRaw results saved to: {RESULTS_FILE}")

    # ─── Step 4: Results Table ───
    print("\n" + "=" * 70)
    print("  STEP 4: TOURNAMENT RESULTS")
    print("=" * 70)

    # Sort by grade then return
    grade_order = {"A": 0, "B": 1, "C": 2, "D": 3, "F": 4}
    results_sorted = sorted(results, key=lambda r: (
        grade_order.get(r.get("grade", "F"), 5),
        -r.get("return_pct", -999),
    ))

    # Print table
    header = (f"{'Grade':5s} {'ID':>4s} {'Strategy':40s} {'Cat':12s} "
              f"{'Trades':>6s} {'Return%':>8s} {'WR%':>6s} {'PF':>6s} "
              f"{'Sharpe':>7s} {'MaxDD%':>7s}")
    sep = "-" * len(header)

    print(f"\n{header}")
    print(sep)

    current_grade = None
    for r in results_sorted:
        grade = r.get("grade", "F")
        if grade != current_grade:
            if current_grade is not None:
                print(sep)
            current_grade = grade

        status = r.get("status", "error")
        name = r.get("name", "?")[:40]
        sid = r.get("research_id", "?")
        cat = r.get("category", "?")[:12]

        if status == "ok":
            print(f"{grade:5s} {str(sid):>4s} {name:40s} {cat:12s} "
                  f"{r['trades']:6d} {r['return_pct']:>+8.2f} "
                  f"{r['win_rate']:>6.1f} {r['profit_factor']:>6.2f} "
                  f"{r['sharpe']:>7.2f} {r['max_dd_pct']:>7.2f}")
        elif status == "NO_SIGNALS":
            print(f"{grade:5s} {str(sid):>4s} {name:40s} {cat:12s} "
                  f"{'0':>6s} {'NO_SIGNALS':>8s} {'':>6s} {'':>6s} "
                  f"{'':>7s} {'':>7s}")
        else:
            err_short = r.get("error", status)[:20]
            print(f"{grade:5s} {str(sid):>4s} {name:40s} {cat:12s} "
                  f"{'':>6s} {err_short:>8s}")

    print(sep)

    # Summary stats
    ok_results = [r for r in results if r.get("status") == "ok"]
    no_signal = [r for r in results if r.get("status") == "NO_SIGNALS"]
    errors = [r for r in results if r.get("status") not in ("ok", "NO_SIGNALS")]

    print(f"\nTotal evaluated:  {len(results)}")
    print(f"  With trades:    {len(ok_results)}")
    print(f"  No signals:     {len(no_signal)}")
    print(f"  Errors:         {len(errors)}")

    for grade_letter in ["A", "B", "C", "D", "F"]:
        count = sum(1 for r in results if r.get("grade") == grade_letter)
        if count > 0:
            print(f"  Grade {grade_letter}:        {count}")

    # Grade A detail
    grade_a = [r for r in results_sorted if r.get("grade") == "A"]
    if grade_a:
        print(f"\n{'=' * 70}")
        print(f"  GRADE A STRATEGIES ({len(grade_a)})")
        print(f"{'=' * 70}")
        for r in grade_a:
            print(f"\n  {r['name']}")
            print(f"    Research ID: {r.get('research_id')}")
            print(f"    Category:    {r.get('category')}")
            print(f"    Return:      {r['return_pct']:+.2f}%")
            print(f"    Trades:      {r['trades']} (W:{r['winning_trades']} L:{r['losing_trades']})")
            print(f"    Win Rate:    {r['win_rate']:.1f}%")
            print(f"    PF:          {r['profit_factor']:.2f}")
            print(f"    Sharpe:      {r['sharpe']:.2f}")
            print(f"    Max DD:      {r['max_dd_pct']:.2f}%")
            print(f"    Avg Trade:   {r['avg_trade_pct']:.3f}%")
            print(f"    Best/Worst:  {r['best_trade_pct']:+.2f}% / {r['worst_trade_pct']:+.2f}%")
            print(f"    Avg Hold:    {r['avg_holding_hours']:.1f} hours")

    profitable = [r for r in ok_results if r.get("return_pct", 0) > 0]
    print(f"\nProfitable strategies: {len(profitable)}/{len(ok_results)}")
    if profitable:
        best = max(profitable, key=lambda r: r["return_pct"])
        print(f"Best performer: {best['name']} ({best['return_pct']:+.2f}%, "
              f"Sharpe {best['sharpe']:.2f})")


if __name__ == "__main__":
    main()
