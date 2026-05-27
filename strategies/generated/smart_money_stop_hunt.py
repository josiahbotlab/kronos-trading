#!/usr/bin/env python3
"""
Smart Money Stop Hunt (Extended Supply/Demand Zones)
====================================================
Auto-generated from: Smart Money Concepts Trading Bot (step by step tutorial)
Category: other
Confidence: 85%

A liquidity-grab strategy that targets the stop-loss levels of conventional supply and demand traders. The algorithm calculates standard supply/demand zones using a 96-bar lookback, then extends the range by 1.5x to identify 'extended highs' and 'extended lows' where retail traders typically place stop losses. The bot enters long positions at extended lows (hunting demand zone sell-stops) or short positions at extended highs (hunting supply zone buy-stops), effectively trading against the expected liquidation levels of S&D strategies.

NOTE: This is auto-generated code from LLM-extracted strategy descriptions.
      Review and tune parameters before live trading.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from strategies.templates.base_strategy import BaseStrategy, CandleData, Signal
import numpy as np


class SmartMoneyStopHunt(BaseStrategy):
    name = "smart_money_stop_hunt"
    version = "0.1"

    def default_params(self) -> dict:
        return {
            "cooldown_bars": 5,
            "emergency_stop_loss_percentage": 5.0,
            "entry_offset_percentage": 0.1,
            "entry_strength": 0.8,
            "extended_lookback_bars": 144,
            "extended_range_multiplier": 1.5,
            "fast_period": 10,
            "liq_percentile": 85,
            "liq_ratio_threshold": 0.6,
            "lookback_bars": 300,
            "max_history": 300,
            "max_hold_bars": 20,
            "max_loss_percentage": 3.0,
            "slow_period": 30,
            "supply_demand_lookback_bars": 96,
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

        # Liquidation cascade detection
        liq_values = self.liq_usd(self.get_param("lookback_bars"))
        nonzero = liq_values[liq_values > 0]
        if len(nonzero) < 20:
            return Signal(direction=None)
        threshold = np.percentile(nonzero, self.get_param("liq_percentile"))
        cascade_active = candle.liquidation_usd >= threshold

        # Moving average trend filter
        fast_ma = self.ema(self.get_param("fast_period")) if self.get_param("fast_period") else None
        slow_ma = self.sma(self.get_param("slow_period")) if self.get_param("slow_period") else None
        ma_ready = fast_ma is not None and slow_ma is not None

        # Entry condition
        if cascade_active and ma_ready:

            # Determine direction from liquidation imbalance
            total_liq = candle.liquidation_usd
            if total_liq > 0:
                ratio_thresh = self.get_param("liq_ratio_threshold")
                short_ratio = candle.short_liq_usd / total_liq
                long_ratio = candle.long_liq_usd / total_liq
                if short_ratio >= ratio_thresh:
                    direction = 1   # shorts rekt = bullish
                elif long_ratio >= ratio_thresh:
                    direction = -1  # longs rekt = bearish
                else:
                    return Signal(direction=None)
            else:
                return Signal(direction=None)

            self._in_trade = True
            self._trade_direction = direction
            self._bars_held = 0
            self._peak = candle.high
            self._trough = candle.low

            return Signal(
                direction=direction,
                strength=self.get_param("entry_strength"),
                tag=f"smart_money_stop_hunt_{'bull' if direction == 1 else 'bear'}",
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
    "supply_demand_lookback_bars": [
        48,
        96,
        192
    ],
    "extended_range_multiplier": [
        0.75,
        1.5,
        2.25,
        3.0
    ],
    "extended_lookback_bars": [
        72,
        144,
        288
    ],
    "entry_offset_percentage": [
        0.05,
        0.1,
        0.15000000000000002,
        0.2
    ],
    "emergency_stop_loss_percentage": [
        2.5,
        5.0,
        7.5,
        10.0
    ],
    "max_loss_percentage": [
        1.5,
        3.0,
        4.5,
        6.0
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
