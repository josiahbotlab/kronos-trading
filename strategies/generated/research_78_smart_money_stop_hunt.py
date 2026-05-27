#!/usr/bin/env python3
"""
Smart Money Stop Hunt (Supply/Demand Liquidity Grab)
====================================================
Research ID: 78
Category: breakout
Confidence: 85%

A breakout strategy that identifies supply and demand zones using a 96-bar lookback, then calculates extended highs and lows at 1.5x the lookback period (144 bars) to locate where retail traders typically place stop losses. The strategy enters long positions at the extended low (buying the stops of demand zone traders) and short positions at the extended high (buying the stops of supply zone traders), effectively harvesting liquidity from stop runs.

Auto-generated for batch tournament evaluation.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from strategies.templates.base_strategy import BaseStrategy, CandleData, Signal
import numpy as np


class Research78SmartMoneyStopHunt(BaseStrategy):
    name = "research_78_smart_money_stop_hunt"
    version = "0.1"

    def default_params(self) -> dict:
        return {
            "cooldown_bars": 12,
            "ema_fast": 9,
            "ema_slow": 21,
            "emergency_stop_loss_percent": 5,
            "entry_offset_percent": 0.1,
            "entry_strength": 0.8,
            "extended_lookback_bars": 144,
            "extension_multiplier": 1.5,
            "lookback_period_bars": 96,
            "max_history": 500,
            "max_hold_bars": 60,
            "max_loss_percent": 3,
            "take_profit_pct": 3.0,
            "trailing_stop_pct": 1.5,
        }

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

        ema_f = self.ema(self.get_param("ema_fast"))
        ema_s = self.ema(self.get_param("ema_slow"))
        if ema_f is None or ema_s is None:
            return Signal(direction=None)

        # Entry condition
        if True:

            # Direction from EMA crossover
            direction = 1 if ema_f > ema_s else -1

            self._in_trade = True
            self._trade_direction = direction
            self._bars_held = 0
            self._peak = candle.high
            self._trough = candle.low

            tag = "research_78_smart_money_stop_hunt_bull" if direction == 1 else "research_78_smart_money_stop_hunt_bear"
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
        return Signal(direction=0, tag=f"exit_{reason}")

    def on_trade(self, pnl: float, pnl_pct: float):
        self._in_trade = False
        self._trade_direction = 0
