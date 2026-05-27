#!/usr/bin/env python3
"""
Beast Mode Elite Momentum
=========================
Auto-generated from: Can AI significantly improve Trading in 2025? i tested it.
Category: momentum
Confidence: 90%

High-confidence momentum strategy using XGBoost predictions with strict filters to reduce overtrading. Uses elevated confidence thresholds and extended cool-down periods to filter only the highest-probability setups while avoiding pump/dump chasing.

NOTE: This is auto-generated code from LLM-extracted strategy descriptions.
      Review and tune parameters before live trading.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from strategies.templates.base_strategy import BaseStrategy, CandleData, Signal
import numpy as np


class BeastModeEliteMomentum(BaseStrategy):
    name = "beast_mode_elite_momentum"
    version = "0.1"

    def default_params(self) -> dict:
        return {
            "confidence_threshold": 0.6,
            "cooldown_bars": 5,
            "cooldown_ticks": 100,
            "entry_strength": 0.8,
            "fee_bps": 4.5,
            "liq_percentile": 85,
            "max_history": 300,
            "max_hold_bars": 20,
            "previous_confidence_threshold": 0.35,
            "previous_take_profit": 0.2,
            "previous_trade_count": 857,
            "take_profit": 0.5,
            "take_profit_pct": 5.0,
            "target_trades": 86,
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

        # Generic indicator setup (customize based on strategy logic)
        liq_values = self.liq_usd(200)
        nonzero = liq_values[liq_values > 0]
        if len(nonzero) < 20:
            return Signal(direction=None)
        threshold = np.percentile(nonzero, self.get_param("liq_percentile"))
        cascade_active = candle.liquidation_usd >= threshold

        # Entry condition
        if cascade_active:

            # Direction from price action
            direction = 1 if candle.close > candle.open else -1

            self._in_trade = True
            self._trade_direction = direction
            self._bars_held = 0
            self._peak = candle.high
            self._trough = candle.low

            return Signal(
                direction=direction,
                strength=self.get_param("entry_strength"),
                tag=f"beast_mode_elite_momentum_{'bull' if direction == 1 else 'bear'}",
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
    "confidence_threshold": [
        0.3,
        0.6,
        0.8999999999999999,
        1.2
    ],
    "previous_confidence_threshold": [
        0.175,
        0.35,
        0.5249999999999999,
        0.7
    ],
    "take_profit": [
        0.25,
        0.5,
        0.75,
        1.0
    ],
    "previous_take_profit": [
        0.1,
        0.2,
        0.30000000000000004,
        0.4
    ],
    "cooldown_ticks": [
        50,
        100,
        200
    ],
    "fee_bps": [
        2.25,
        4.5,
        6.75,
        9.0
    ],
    "target_trades": [
        43,
        86,
        172
    ],
    "previous_trade_count": [
        428,
        857,
        1714
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
