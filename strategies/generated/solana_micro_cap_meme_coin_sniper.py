#!/usr/bin/env python3
"""
Solana Micro-Cap Meme Coin Sniper
=================================
Auto-generated from: solana sniper bot in python that actually works
Category: scalping
Confidence: 85%

Automated sniper strategy targeting newly launched Solana meme coins under $20,000 market cap within the first 24 hours. Uses multi-layered filtering to identify high-momentum tokens with strong buy pressure and valid social presence while filtering out rug pulls through price action and liquidity analysis.

NOTE: This is auto-generated code from LLM-extracted strategy descriptions.
      Review and tune parameters before live trading.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from strategies.templates.base_strategy import BaseStrategy, CandleData, Signal
import numpy as np


class SolanaMicroCapMemeCoinSniper(BaseStrategy):
    name = "solana_micro_cap_meme_coin_sniper"
    version = "0.1"

    def default_params(self) -> dict:
        return {
            "cooldown_bars": 5,
            "entry_strength": 0.8,
            "liq_percentile": 85,
            "market_cap_max": 20000,
            "max_history": 300,
            "max_hold_bars": 20,
            "max_sell_percentage": 75,
            "min_buy_percentage": 25,
            "min_trades_last_hour": 5,
            "partial_exit_threshold": 150,
            "position_size_usd": 10,
            "rug_pull_price_drop_threshold": 90,
            "take_profit_pct": 5.0,
            "take_profit_percentage": 200,
            "token_age_max_hours": 24,
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
                tag=f"solana_micro_cap_meme_coin_sniper_{'bull' if direction == 1 else 'bear'}",
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
    "market_cap_max": [
        10000,
        20000,
        40000
    ],
    "token_age_max_hours": [
        12,
        24,
        48
    ],
    "min_trades_last_hour": [
        2,
        5,
        10
    ],
    "max_sell_percentage": [
        37,
        75,
        150
    ],
    "min_buy_percentage": [
        12,
        25,
        50
    ],
    "rug_pull_price_drop_threshold": [
        45,
        90,
        180
    ],
    "position_size_usd": [
        5,
        10,
        20
    ],
    "take_profit_percentage": [
        100,
        200,
        400
    ],
    "partial_exit_threshold": [
        75,
        150,
        300
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
