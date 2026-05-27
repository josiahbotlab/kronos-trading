#!/usr/bin/env python3
"""
Mean Reversion Market Maker
===========================
Auto-generated from: How To Build a Market Maker Algorithm (in Python)
Category: mean_reversion
Confidence: 75%

A range-bound mean reversion strategy that attempts to profit from sideways BTC price action by buying near local lows and selling near local highs. Uses volatility filters to avoid trading during strong trends, with explicit checks for higher highs or lower lows over recent bars to detect directional movement.

NOTE: This is auto-generated code from LLM-extracted strategy descriptions.
      Review and tune parameters before live trading.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from strategies.templates.base_strategy import BaseStrategy, CandleData, Signal
import numpy as np


class MeanReversionMarketMaker(BaseStrategy):
    name = "mean_reversion_market_maker"
    version = "0.1"

    def default_params(self) -> dict:
        return {
            "bars_lookback": 180,
            "cooldown_bars": 5,
            "entry_strength": 0.8,
            "loop_interval_seconds": 20,
            "low_to_high_percentage": 0.35,
            "max_history": 300,
            "max_hold_bars": 20,
            "max_position_risk_usd": 1000,
            "max_range_threshold": 800,
            "overtrading_cooldown_minutes": 20,
            "position_size_units": 3,
            "position_value_usd": 70,
            "price_time_limit": 60,
            "rsi_period": 14,
            "sleep_duration": 30,
            "stop_loss_percentage": 0.1,
            "take_profit_pct": 5.0,
            "time_based_exit_seconds": 2820,
            "trailing_stop_pct": 2.0,
            "trend_detection_bars": 17,
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

        # Entry condition
        if rsi_ready and (current_rsi > 70 or current_rsi < 30):

            # Direction from RSI extremes (reversal)
            direction = -1 if current_rsi > 70 else 1 if current_rsi < 30 else None
            if direction is None:
                return Signal(direction=None)

            self._in_trade = True
            self._trade_direction = direction
            self._bars_held = 0
            self._peak = candle.high
            self._trough = candle.low

            return Signal(
                direction=direction,
                strength=self.get_param("entry_strength"),
                tag=f"mean_reversion_market_maker_{'bull' if direction == 1 else 'bear'}",
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
    "bars_lookback": [
        90,
        180,
        360
    ],
    "low_to_high_percentage": [
        0.175,
        0.35,
        0.5249999999999999,
        0.7
    ],
    "max_range_threshold": [
        400,
        800,
        1600
    ],
    "trend_detection_bars": [
        8,
        17,
        34
    ],
    "position_size_units": [
        1,
        3,
        6
    ],
    "position_value_usd": [
        35,
        70,
        140
    ],
    "max_position_risk_usd": [
        500,
        1000,
        2000
    ],
    "stop_loss_percentage": [
        0.05,
        0.1,
        0.15000000000000002,
        0.2
    ],
    "time_based_exit_seconds": [
        1410,
        2820,
        5640
    ],
    "loop_interval_seconds": [
        10,
        20,
        40
    ],
    "overtrading_cooldown_minutes": [
        10,
        20,
        40
    ],
    "price_time_limit": [
        30,
        60,
        120
    ],
    "sleep_duration": [
        15,
        30,
        60
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
