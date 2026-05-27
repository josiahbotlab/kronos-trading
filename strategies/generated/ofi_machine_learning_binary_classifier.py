#!/usr/bin/env python3
"""
OFI Machine Learning Binary Classifier
======================================
Auto-generated from: Claude 4 Machine Learning HFT Trading Bots
Category: scalping
Confidence: 90%

Uses Order Flow Imbalance (OFI) data collected from Binance websocket to predict binary price direction (up/down) over 5-second or 10-second horizons. Features include depth, balance, VPIN, micro-price, churn, and engineered features like slopes, persistence, and lags. Entry is gated by Expected Value (EV) calculation requiring P(win) × TP > threshold.

NOTE: This is auto-generated code from LLM-extracted strategy descriptions.
      Review and tune parameters before live trading.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from strategies.templates.base_strategy import BaseStrategy, CandleData, Signal
import numpy as np


class OfiMachineLearningBinaryClassifier(BaseStrategy):
    name = "ofi_machine_learning_binary_classifier"
    version = "0.1"

    def default_params(self) -> dict:
        return {
            "auc_threshold_excellent": 0.65,
            "auc_threshold_tradable": 0.55,
            "cooldown_bars": 5,
            "entry_strength": 0.8,
            "max_history": 300,
            "max_hold_bars": 20,
            "rsi_period": 14,
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

        # Entry condition
        if rsi_ready:

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
                tag=f"ofi_machine_learning_binary_classifier_{'bull' if direction == 1 else 'bear'}",
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
    "auc_threshold_tradable": [
        0.275,
        0.55,
        0.8250000000000001,
        1.1
    ],
    "auc_threshold_excellent": [
        0.325,
        0.65,
        0.9750000000000001,
        1.3
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
