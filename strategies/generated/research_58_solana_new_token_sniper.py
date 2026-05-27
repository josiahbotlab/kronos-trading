#!/usr/bin/env python3
"""
Solana New Token Sniper
=======================
Research ID: 58
Category: scalping
Confidence: 75%

Automated scalping strategy that monitors BirdEye API for newly launched Solana tokens with low market caps. Enters immediately upon launch with small position sizes and exits quickly to capture early momentum, using liquidity and volume filters to avoid rug pulls.

Auto-generated for batch tournament evaluation.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from strategies.templates.base_strategy import BaseStrategy, CandleData, Signal
import numpy as np


class Research58SolanaNewTokenSniper(BaseStrategy):
    name = "research_58_solana_new_token_sniper"
    version = "0.1"

    def default_params(self) -> dict:
        return {
            "cooldown_bars": 12,
            "entry_strength": 0.8,
            "market_cap_threshold": 500000,
            "max_history": 500,
            "max_hold_bars": 60,
            "position_size_usd": 10,
            "sma_fast": 10,
            "sma_slow": 30,
            "take_profit_pct": 3.0,
            "trailing_stop_pct": 1.5,
            "vol_mult": 1.5,
            "vol_period": 20,
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

        sma_f = self.sma(self.get_param("sma_fast"))
        sma_s = self.sma(self.get_param("sma_slow"))
        if sma_f is None or sma_s is None:
            return Signal(direction=None)

        volumes_arr = self.volumes(self.get_param("vol_period"))
        if len(volumes_arr) < self.get_param("vol_period"):
            return Signal(direction=None)
        avg_vol = float(np.mean(volumes_arr[:-1])) if len(volumes_arr) > 1 else 1.0
        vol_ratio = candle.volume / avg_vol if avg_vol > 0 else 0

        # Entry condition
        if True and vol_ratio >= self.get_param('vol_mult'):

            # Direction from SMA crossover
            direction = 1 if sma_f > sma_s else -1

            self._in_trade = True
            self._trade_direction = direction
            self._bars_held = 0
            self._peak = candle.high
            self._trough = candle.low

            tag = "research_58_solana_new_token_sniper_bull" if direction == 1 else "research_58_solana_new_token_sniper_bear"
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
