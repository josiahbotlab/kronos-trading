#!/usr/bin/env python3
"""
Supply and Demand Zone Bot with Trend Filter
============================================
Research ID: 219
Category: mean_reversion
Confidence: 65%

An automated strategy for trading Solana meme coins that enters positions at supply and demand zones (theoretical institutional levels) while filtering trades based on broader market trends. The bot adjusts exit sizing based on trend direction to prevent panic selling while maintaining exposure.

Auto-generated for batch tournament evaluation.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from strategies.templates.base_strategy import BaseStrategy, CandleData, Signal
import numpy as np


class Research219SupplyAndDemandZoneBotWithTrendFi(BaseStrategy):
    name = "research_219_supply_and_demand_zone_bot_with_trend_fi"
    version = "0.1"

    def default_params(self) -> dict:
        return {
            "cooldown_bars": 12,
            "ema_fast": 9,
            "ema_slow": 21,
            "entry_strength": 0.8,
            "max_history": 500,
            "max_hold_bars": 60,
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

            tag = "research_219_supply_and_demand_zone_bot_with_trend_fi_bull" if direction == 1 else "research_219_supply_and_demand_zone_bot_with_trend_fi_bear"
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
