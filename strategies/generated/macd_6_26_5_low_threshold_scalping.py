#!/usr/bin/env python3
"""
MACD 6/26/5 Low Threshold Scalping
==================================
Auto-generated from: i cracked polymarket with claude code (opus 4.6)
Category: scalping
Confidence: 75%

High-frequency scalping variant using MACD(6,26,5) configuration with a lower histogram entry threshold of >10 for 5-minute Polymarket contracts. Captures more frequent signals (104,000 trades) resulting in higher absolute P&L ($119,000) with 60.18% win rate and 6.18% edge, but requires strict drawdown controls.

NOTE: This is auto-generated code from LLM-extracted strategy descriptions.
      Review and tune parameters before live trading.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from strategies.templates.base_strategy import BaseStrategy, CandleData, Signal
import numpy as np


class Macd6265LowThresholdScalping(BaseStrategy):
    name = "macd_6_26_5_low_threshold_scalping"
    version = "0.1"

    def default_params(self) -> dict:
        return {
            "cooldown_bars": 5,
            "entry_strength": 0.8,
            "fast_ema_period": 6,
            "histogram_threshold": 10,
            "liq_percentile": 85,
            "max_drawdown": 402,
            "max_history": 300,
            "max_hold_bars": 20,
            "signal_line_period": 5,
            "slow_ema_period": 26,
            "take_profit_pct": 5.0,
            "total_pnl": 119000,
            "total_trades": 104000,
            "trailing_stop_pct": 2.0,
            "z_score": 70.8,
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
                tag=f"macd_6_26_5_low_threshold_scalping_{'bull' if direction == 1 else 'bear'}",
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
    "fast_ema_period": [
        3,
        6,
        12
    ],
    "slow_ema_period": [
        13,
        26,
        52
    ],
    "signal_line_period": [
        2,
        5,
        10
    ],
    "histogram_threshold": [
        5,
        10,
        20
    ],
    "total_trades": [
        52000,
        104000,
        208000
    ],
    "total_pnl": [
        59500,
        119000,
        238000
    ],
    "z_score": [
        35.4,
        70.8,
        106.19999999999999,
        141.6
    ],
    "max_drawdown": [
        201,
        402,
        804
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
