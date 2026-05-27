#!/usr/bin/env python3
"""
Direction Strength / Speed-to-Fill Scalping
===========================================
Auto-generated from: Claude Sonnet 4.5 Built Me 4 HFT Trading Bots
Category: scalping
Confidence: 85%

High-frequency scalping strategy that places simultaneous small test orders ($10) at configurable bid and ask levels to measure which fills first. If the bid fills first, it indicates sell pressure (short signal); if the ask fills first, it indicates buy pressure (long signal). Enters a larger directional position immediately after the test fill.

NOTE: This is auto-generated code from LLM-extracted strategy descriptions.
      Review and tune parameters before live trading.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from strategies.templates.base_strategy import BaseStrategy, CandleData, Signal
import numpy as np


class DirectionStrengthSpeedToFillScalpin(BaseStrategy):
    name = "direction_strength_speed_to_fill_scalpin"
    version = "0.1"

    def default_params(self) -> dict:
        return {
            "cool_down_seconds": 300,
            "cooldown_bars": 5,
            "entry_strength": 0.8,
            "fast_period": 10,
            "max_history": 300,
            "max_hold_bars": 20,
            "real_trade_leverage": 10,
            "real_trade_margin_usd": 50,
            "real_trade_notional": 500,
            "slow_period": 30,
            "take_profit_pct": 5.0,
            "test_order_size_usd": 10,
            "trailing_stop_pct": 2.0,
        }

    def on_init(self):
        self._in_trade = False
        self._trade_direction = 0
        self._bars_held = 0
        self._peak = 0.0
        self._trough = float("inf")
        self._cooldown = 0

    def on_candle(self, candle: CandleData) -> Signal:
        if self._cooldown > 0:
            self._cooldown -= 1

        # --- IN POSITION: manage exits ---
        if self._in_trade:
            self._bars_held += 1

            if self._trade_direction == 1:
                self._peak = max(self._peak, candle.high)
                stop = self._peak * (1 - self.get_param("trailing_stop_pct") / 100)
                if candle.low <= stop:
                    return self._exit("trailing_stop")
            else:
                self._trough = min(self._trough, candle.low)
                stop = self._trough * (1 + self.get_param("trailing_stop_pct") / 100)
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

        # Moving average trend filter
        fast_ma = self.ema(self.get_param("fast_period")) if self.get_param("fast_period") else None
        slow_ma = self.sma(self.get_param("slow_period")) if self.get_param("slow_period") else None
        ma_ready = fast_ma is not None and slow_ma is not None

        # Entry condition
        if ma_ready:

            # Direction from moving average crossover
            direction = 1 if fast_ma > slow_ma else -1

            self._in_trade = True
            self._trade_direction = direction
            self._bars_held = 0
            self._peak = candle.high
            self._trough = candle.low

            return Signal(
                direction=direction,
                strength=self.get_param("entry_strength"),
                tag=f"direction_strength_speed_to_fill_scalpin_{'bull' if direction == 1 else 'bear'}",
            )

        return Signal(direction=None)

    def _exit(self, reason: str) -> Signal:
        self._in_trade = False
        self._trade_direction = 0
        self._cooldown = self.get_param("cooldown_bars")
        return Signal(direction=0, tag=f"exit_{reason}")

    def on_trade(self, pnl: float, pnl_pct: float):
        self._in_trade = False
        self._trade_direction = 0


# Parameter ranges for robustness testing
PARAM_RANGES = {
    "test_order_size_usd": [
        5,
        10,
        20
    ],
    "real_trade_margin_usd": [
        25,
        50,
        100
    ],
    "real_trade_leverage": [
        5,
        10,
        20
    ],
    "real_trade_notional": [
        250,
        500,
        1000
    ],
    "cool_down_seconds": [
        150,
        300,
        600
    ],
    "trailing_stop_pct": [
        1.0,
        1.5,
        2.0,
        3.0
    ],
    "take_profit_pct": [
        3.0,
        5.0,
        8.0,
        10.0
    ],
    "max_hold_bars": [
        10,
        20,
        30
    ]
}
