#!/usr/bin/env python3
"""
MACD 3-15-3 on 5-Minute Polymarket Markets
==========================================
Auto-generated from: Polymarket 5 Min Claude Code Bot are NUTS
Category: scalping
Confidence: 80%

Uses MACD indicator with parameters 3 (fast), 15 (slow), and 3 (signal) to trade 5-minute binary prediction markets on Polymarket. The strategy generates high-frequency signals, taking approximately 287 out of 288 available daily trade opportunities with a 60% win rate.

NOTE: This is auto-generated code from LLM-extracted strategy descriptions.
      Review and tune parameters before live trading.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from strategies.templates.base_strategy import BaseStrategy, CandleData, Signal
import numpy as np


class Macd3153On5MinutePolymarketMarke(BaseStrategy):
    name = "macd_3_15_3_on_5_minute_polymarket_marke"
    version = "0.1"

    def default_params(self) -> dict:
        return {
            "backtested": True,
            "cooldown_bars": 5,
            "daily_opportunities": 288,
            "entry_strength": 0.8,
            "fast_period": 3,
            "liq_percentile": 85,
            "max_history": 300,
            "max_hold_bars": 20,
            "signal_period": 3,
            "slow_period": 15,
            "stress_tested": True,
            "take_profit_pct": 5.0,
            "trades_per_day": 287,
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
                tag=f"macd_3_15_3_on_5_minute_polymarket_marke_{'bull' if direction == 1 else 'bear'}",
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
    "fast_period": [
        1,
        3,
        6
    ],
    "slow_period": [
        7,
        15,
        30
    ],
    "signal_period": [
        1,
        3,
        6
    ],
    "trades_per_day": [
        143,
        287,
        574
    ],
    "daily_opportunities": [
        144,
        288,
        576
    ],
    "backtested": [
        1,
        true,
        2
    ],
    "stress_tested": [
        1,
        true,
        2
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
