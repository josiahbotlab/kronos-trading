#!/usr/bin/env python3
"""
Hyperliquid Liquidation Grid (Hyperlick)
========================================
Auto-generated from: Most Claude Bots are Slop. This is how to actually build trading bots
Category: scalping
Confidence: 95%

A grid scalping bot that monitors Hyperliquid liquidation clusters for the HYPE token. It identifies the largest whale liquidation (minimum $100K) within 10% of current price and places a ladder of three limit orders just beyond that liquidation level (0.2% buffer) with 0.5% spacing to catch the cascade move. The bot places grids on both long and short sides simultaneously, entering when price hits the liquidation cluster and exiting on fixed 10% stop loss or take profit.

NOTE: This is auto-generated code from LLM-extracted strategy descriptions.
      Review and tune parameters before live trading.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from strategies.templates.base_strategy import BaseStrategy, CandleData, Signal
import numpy as np


class HyperliquidLiquidationGrid(BaseStrategy):
    name = "hyperliquid_liquidation_grid"
    version = "0.1"

    def default_params(self) -> dict:
        return {
            "buffer_beyond_whale_percent": 0.2,
            "cluster_range_percent": 10,
            "cooldown_bars": 5,
            "entry_strength": 0.8,
            "grid_orders_per_side": 3,
            "grid_spacing_percent": 0.5,
            "leverage": 10,
            "liq_percentile": 85,
            "liq_ratio_threshold": 0.6,
            "lookback_bars": 300,
            "max_history": 300,
            "max_hold_bars": 20,
            "minimum_liquidation_size": 100000,
            "stop_loss_percent": 10,
            "take_profit_pct": 5.0,
            "take_profit_percent": 10,
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
                tag=f"hyperliquid_liquidation_grid_{'bull' if direction == 1 else 'bear'}",
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
    "minimum_liquidation_size": [
        50000,
        100000,
        200000
    ],
    "cluster_range_percent": [
        5,
        10,
        20
    ],
    "buffer_beyond_whale_percent": [
        0.1,
        0.2,
        0.30000000000000004,
        0.4
    ],
    "grid_orders_per_side": [
        1,
        3,
        6
    ],
    "grid_spacing_percent": [
        0.25,
        0.5,
        0.75,
        1.0
    ],
    "leverage": [
        5,
        10,
        20
    ],
    "stop_loss_percent": [
        5,
        10,
        20
    ],
    "take_profit_percent": [
        5,
        10,
        20
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
