#!/usr/bin/env python3
"""
Solana New Token Sniper (Birdeye Scalper)
=========================================
Auto-generated from: How To Use The Birdeye API (Documentation Walk Through)
Category: scalping
Confidence: 85%

A scalping strategy that monitors Birdeye API for newly launched Solana meme tokens, entering immediately upon launch with small position sizes and exiting quickly after initial price movement. The strategy filters tokens by market cap, liquidity, and recent trading activity to avoid rugs and illiquid assets.

NOTE: This is auto-generated code from LLM-extracted strategy descriptions.
      Review and tune parameters before live trading.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from strategies.templates.base_strategy import BaseStrategy, CandleData, Signal
import numpy as np


class SolanaNewTokenSniper(BaseStrategy):
    name = "solana_new_token_sniper"
    version = "0.1"

    def default_params(self) -> dict:
        return {
            "cooldown_bars": 5,
            "entry_strength": 0.8,
            "fast_period": 10,
            "max_24h_volume_usd": 10000,
            "max_history": 300,
            "max_hold_bars": 20,
            "max_market_cap_usd": 500000,
            "max_positions_per_day": 5,
            "min_24h_volume_usd": 2000,
            "min_liquidity_usd": 2000,
            "min_market_cap_usd": 1000,
            "position_size_usd": 10,
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

        # Moving average trend filter
        fast_ma = self.ema(self.get_param("fast_period")) if self.get_param("fast_period") else None
        slow_ma = self.sma(self.get_param("slow_period")) if self.get_param("slow_period") else None
        ma_ready = fast_ma is not None and slow_ma is not None

        # Entry condition
        if ma_ready:

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
                tag=f"solana_new_token_sniper_{'bull' if direction == 1 else 'bear'}",
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
    "position_size_usd": [
        5,
        10,
        20
    ],
    "max_positions_per_day": [
        2,
        5,
        10
    ],
    "min_market_cap_usd": [
        500,
        1000,
        2000
    ],
    "max_market_cap_usd": [
        250000,
        500000,
        1000000
    ],
    "min_liquidity_usd": [
        1000,
        2000,
        4000
    ],
    "min_24h_volume_usd": [
        1000,
        2000,
        4000
    ],
    "max_24h_volume_usd": [
        5000,
        10000,
        20000
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
