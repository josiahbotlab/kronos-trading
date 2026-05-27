#!/usr/bin/env python3
"""
Liquidation Cascade Momentum on 5-Minute Binaries
=================================================
Auto-generated from: Claude Code Built me an Actual Polymarket Trading Bot
Category: momentum
Confidence: 70%

A high-frequency momentum strategy that trades 5-minute binary markets on Polymarket based on liquidation cascades observed on Hyperliquid. When total liquidations reach a threshold ($25k-$100k), indicating forced position closures and potential momentum, the bot enters a directional bet assuming continued price movement in the liquidation direction. Short liquidations trigger long entries (expecting price to continue up), while long liquidations trigger short entries. Positions are automatically held until the 5-minute expiry.

NOTE: This is auto-generated code from LLM-extracted strategy descriptions.
      Review and tune parameters before live trading.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from strategies.templates.base_strategy import BaseStrategy, CandleData, Signal
import numpy as np


class LiquidationCascadeMomentumOn5Minute(BaseStrategy):
    name = "liquidation_cascade_momentum_on_5_minute"
    version = "0.1"

    def default_params(self) -> dict:
        return {
            "cooldown_bars": 5,
            "entry_strength": 0.8,
            "exposure_per_trade_usd": 25,
            "liq_percentile": 85,
            "liq_ratio_threshold": 0.6,
            "liquidation_threshold_max_usd": 100000,
            "liquidation_threshold_min_usd": 25000,
            "lookback_bars": 300,
            "max_history": 300,
            "max_hold_bars": 20,
            "max_trades_per_day": 288,
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

        # Entry condition
        if cascade_active:

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
                tag=f"liquidation_cascade_momentum_on_5_minute_{'bull' if direction == 1 else 'bear'}",
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
    "liquidation_threshold_min_usd": [
        12500,
        25000,
        50000
    ],
    "liquidation_threshold_max_usd": [
        50000,
        100000,
        200000
    ],
    "exposure_per_trade_usd": [
        12,
        25,
        50
    ],
    "max_trades_per_day": [
        144,
        288,
        576
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
