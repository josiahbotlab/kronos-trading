#!/usr/bin/env python3
"""
[Strategy Name] v1.0
====================
Source: [Moon Dev video title / URL]
Confidence: [50-100]%

[Brief description of the method: what market condition it targets,
what the entry/exit logic is, and why it works.]

Transcript insight: "[Key quote from the video]"
Web research: [Any additional research that informed the implementation]
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from strategies.templates.base_strategy import BaseStrategy, CandleData, Signal
import numpy as np
import logging

_log = logging.getLogger("strategy.RENAME_ME")


class RenameMe(BaseStrategy):
    """
    [One-line description of the strategy.]

    Replace 'RENAME_ME' and 'RenameMe' with your strategy name.
    The `name` attribute is what the engine uses to load this strategy.
    """

    name = "rename_me"       # Must match the --strategy CLI argument
    version = "1.0"

    def default_params(self) -> dict:
        """
        All tunable parameters go here.
        Use get_param() to read them in on_candle() — never hardcode values.
        """
        return {
            # ── Entry conditions ──
            "entry_strength": 0.7,          # Signal strength for position sizing (0.0-1.0)
            "min_history": 50,              # Candles needed before generating signals
            "lookback": 20,                 # Bars to look back for pattern detection

            # ── Exit conditions ──
            "stop_loss_pct": 2.0,           # Stop loss percentage
            "take_profit_pct": 4.0,         # Take profit percentage
            "max_hold_bars": 24,            # Max candles to hold a position
            "cooldown_bars": 5,             # Bars to wait after closing before re-entry

            # ── Filters ──
            # "rsi_period": 14,             # Uncomment filters as needed
            # "rsi_oversold": 30,
            # "rsi_overbought": 70,

            # ── Internal ──
            "max_history": 300,             # Rolling candle buffer size
        }

    def on_init(self):
        """Called once before candle processing starts."""
        self._in_trade = False
        self._trade_dir = 0           # 1=long, -1=short
        self._entry_price = 0.0
        self._bars_held = 0
        self._cooldown = 0
        self._diag_count = 0          # Diagnostic logging counter

    def on_candle(self, candle: CandleData) -> Signal:
        """
        Called for each new candle. Return a Signal:
            Signal(direction=1)    → go long
            Signal(direction=-1)   → go short
            Signal(direction=0)    → close position
            Signal(direction=None) → hold / do nothing
        """
        if self._cooldown > 0:
            self._cooldown -= 1

        # ── IN POSITION: manage exits ──
        if self._in_trade:
            self._bars_held += 1
            return self._manage_position(candle)

        # ── NO POSITION: look for entries ──
        if self._cooldown > 0:
            return Signal(direction=None)

        if len(self._candle_history) < self.get_param("min_history"):
            return Signal(direction=None)

        self._diag_count += 1

        # ┌─────────────────────────────────────────────────┐
        # │  ENTRY LOGIC — Replace this section             │
        # │                                                 │
        # │  Compute your indicators, detect your pattern,  │
        # │  and decide whether to enter long or short.     │
        # └─────────────────────────────────────────────────┘

        # Example: detect a condition
        entry_signal = self._detect_entry(candle)

        # Diagnostic logging every 12 candles (~1 hour on 5m)
        if self._diag_count % 12 == 0:
            _log.info(
                f"DIAG #{self._diag_count}: close={candle.close:.0f} "
                f"entry_signal={entry_signal} "
                # Add your key metrics here:
                # f"indicator={value:.2f} "
                f"liq={candle.liquidation_usd:.0f}"
            )

        if entry_signal == 0:
            return Signal(direction=None)

        # Log entry detection (these are rare, always log)
        _log.info(f"ENTRY DETECTED: dir={entry_signal} close={candle.close:.0f}")

        # ┌─────────────────────────────────────────────────┐
        # │  FILTERS — Add confirmation checks here         │
        # │                                                 │
        # │  RSI, volume, regime, liquidation boost, etc.   │
        # └─────────────────────────────────────────────────┘

        # Example RSI filter (uncomment and adjust):
        # rsi_val = self.rsi(self.get_param("rsi_period"))
        # if rsi_val is not None:
        #     if entry_signal == 1 and rsi_val > self.get_param("rsi_overbought"):
        #         return Signal(direction=None)  # Too overbought for long
        #     if entry_signal == -1 and rsi_val < self.get_param("rsi_oversold"):
        #         return Signal(direction=None)  # Too oversold for short

        # Enter position
        self._in_trade = True
        self._trade_dir = entry_signal
        self._entry_price = candle.close
        self._bars_held = 0

        return Signal(
            direction=entry_signal,
            strength=self.get_param("entry_strength"),
            tag=f"{'long' if entry_signal == 1 else 'short'}_entry",
        )

    def _detect_entry(self, candle: CandleData) -> int:
        """
        Core entry detection logic.
        Returns: 1 for long, -1 for short, 0 for no signal.

        Replace this with your Moon Dev method implementation.
        """
        # Example placeholder: z-score mean reversion
        lookback = self.get_param("lookback")
        closes = self.closes(lookback)
        if len(closes) < lookback:
            return 0

        mean = float(np.mean(closes))
        std = float(np.std(closes, ddof=1))
        if std < 1e-8:
            return 0

        zscore = (candle.close - mean) / std

        # Replace with your actual entry logic
        # if zscore > 2.5:
        #     return -1  # Short the spike
        # if zscore < -2.5:
        #     return 1   # Long the dip

        return 0  # No signal (placeholder — remove this line when implementing)

    def _manage_position(self, candle: CandleData) -> Signal:
        """
        Position management: stop loss, take profit, max hold.
        Adjust or replace with trailing stops, mean reversion exits, etc.
        """
        sl_pct = self.get_param("stop_loss_pct") / 100
        tp_pct = self.get_param("take_profit_pct") / 100

        if self._trade_dir == 1:  # Long
            if candle.low <= self._entry_price * (1 - sl_pct):
                return self._exit("stop_loss")
            if candle.high >= self._entry_price * (1 + tp_pct):
                return self._exit("take_profit")
        else:  # Short
            if candle.high >= self._entry_price * (1 + sl_pct):
                return self._exit("stop_loss")
            if candle.low <= self._entry_price * (1 - tp_pct):
                return self._exit("take_profit")

        if self._bars_held >= self.get_param("max_hold_bars"):
            return self._exit("max_hold")

        return Signal(direction=None)

    def _exit(self, reason: str) -> Signal:
        """Close position with reason tag."""
        self._in_trade = False
        self._trade_dir = 0
        self._cooldown = self.get_param("cooldown_bars")
        return Signal(direction=0, tag=f"exit_{reason}")

    def on_trade(self, pnl: float, pnl_pct: float):
        """Called after a trade closes. Reset state."""
        self._in_trade = False
        self._trade_dir = 0


# Optional: Define parameter ranges for robustness testing
# The robustness suite will test all combinations
PARAM_RANGES = {
    "lookback": [15, 20, 30],
    "stop_loss_pct": [1.5, 2.0, 3.0],
    "take_profit_pct": [3.0, 4.0, 6.0],
    "max_hold_bars": [12, 24, 36],
}
