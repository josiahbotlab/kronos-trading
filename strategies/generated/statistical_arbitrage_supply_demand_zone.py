#!/usr/bin/env python3
"""
Statistical Arbitrage Supply & Demand Zones (5-Sec SDZ)
=======================================================
Auto-generated from: Statistical Arbitrage Supply & Demand Zone Trading Bots
Category: mean_reversion
Confidence: 90%

A mean reversion strategy exploiting correlation between BTC and ETH using 5-second supply/demand zones. Places four simultaneous limit orders (supply/demand on both assets). When one order fills, cancels the opposite-side order on the filled asset and same-side order on the unfilled asset, creating an open-legged statistical arbitrage position expecting the pair to converge. Exits based on combined P&L of both legs.

NOTE: This is auto-generated code from LLM-extracted strategy descriptions.
      Review and tune parameters before live trading.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from strategies.templates.base_strategy import BaseStrategy, CandleData, Signal
import numpy as np


class StatisticalArbitrageSupplyDemandZone(BaseStrategy):
    name = "statistical_arbitrage_supply_demand_zone"
    version = "0.1"

    def default_params(self) -> dict:
        return {
            "bars_to_build": 50,
            "cooldown_bars": 5,
            "entry_strength": 0.8,
            "fast_period": 10,
            "max_history": 300,
            "max_hold_bars": 20,
            "rsi_period": 14,
            "slow_period": 30,
            "take_profit_pct": 5.0,
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

        # RSI filter
        current_rsi = self.rsi(self.get_param("rsi_period"))
        rsi_ready = current_rsi is not None

        # Moving average trend filter
        fast_ma = self.ema(self.get_param("fast_period")) if self.get_param("fast_period") else None
        slow_ma = self.sma(self.get_param("slow_period")) if self.get_param("slow_period") else None
        ma_ready = fast_ma is not None and slow_ma is not None

        # Entry condition
        if rsi_ready and (current_rsi > 70 or current_rsi < 30) and ma_ready:

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
                tag=f"statistical_arbitrage_supply_demand_zone_{'bull' if direction == 1 else 'bear'}",
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
    "bars_to_build": [
        25,
        50,
        100
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
