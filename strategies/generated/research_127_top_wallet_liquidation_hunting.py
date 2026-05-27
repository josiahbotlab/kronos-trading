#!/usr/bin/env python3
"""
Top Wallet Liquidation Hunting
==============================
Research ID: 127
Category: momentum
Confidence: 70%

Monitor liquidation levels of Hyperliquid's largest depositors (wallets with $1M-$500M deposits) to time trade entries when large positions approach forced liquidation. Enter trades when major players are near liquidation (e.g., $10M XRP position at 2.82% from liq price), using these forced liquidations as optimal entry timing signals.

Auto-generated for batch tournament evaluation.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from strategies.templates.base_strategy import BaseStrategy, CandleData, Signal
import numpy as np


class Research127TopWalletLiquidationHunting(BaseStrategy):
    name = "research_127_top_wallet_liquidation_hunting"
    version = "0.1"

    def default_params(self) -> dict:
        return {
            "account_survivor_threshold": 10000,
            "cooldown_bars": 12,
            "entry_strength": 0.8,
            "liq_percentile": 85,
            "max_deposit_usd": 500000000,
            "max_history": 500,
            "max_hold_bars": 60,
            "min_deposit_usd": 1000000,
            "position_size_example_usd": 10000000,
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

        # Liquidation cascade detection
        liq_values = self.liq_usd(200)
        nonzero = liq_values[liq_values > 0]
        if len(nonzero) < 20:
            cascade_active = False
        else:
            threshold = np.percentile(nonzero, self.get_param("liq_percentile"))
            cascade_active = candle.liquidation_usd >= threshold

        # Entry condition
        if cascade_active:

            # Direction from liquidation imbalance
            total_liq = candle.liquidation_usd
            if total_liq > 0:
                short_ratio = candle.short_liq_usd / total_liq
                if short_ratio > 0.6:
                    direction = 1   # Shorts rekt = bullish
                elif short_ratio < 0.4:
                    direction = -1  # Longs rekt = bearish
                else:
                    return Signal(direction=None)
            else:
                return Signal(direction=None)

            self._in_trade = True
            self._trade_direction = direction
            self._bars_held = 0
            self._peak = candle.high
            self._trough = candle.low

            tag = "research_127_top_wallet_liquidation_hunting_bull" if direction == 1 else "research_127_top_wallet_liquidation_hunting_bear"
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
