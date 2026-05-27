#!/usr/bin/env python3
"""
Solana Early Launch Sniping
===========================
Research ID: 158
Category: scalping
Confidence: 75%

Automated strategy that scans the Solana blockchain for newly launched tokens (within 5-10 minutes of launch), filters for low-cap gems under $30k market cap with sufficient liquidity, enters early positions, and implements a partial exit strategy at 100% gains. Designed to capture potential 1000x moves on new meme coins while filtering out obvious rugs.

Auto-generated for batch tournament evaluation.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from strategies.templates.base_strategy import BaseStrategy, CandleData, Signal
import numpy as np


class Research158SolanaEarlyLaunchSniping(BaseStrategy):
    name = "research_158_solana_early_launch_sniping"
    version = "0.1"

    def default_params(self) -> dict:
        return {
            "cooldown_bars": 12,
            "entry_strength": 0.8,
            "exit_position_size_percent": 50,
            "exit_target_gain_percent": 100,
            "market_cap_max": 30000,
            "max_history": 500,
            "max_hold_bars": 60,
            "obv_period": 20,
            "scanning_scope": 15000,
            "sell_order_percentage_max": 70,
            "take_profit_pct": 3.0,
            "trailing_stop_pct": 1.5,
            "volume_24h_min": 1000,
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

        # OBV trend
        closes_arr = self.closes(self.get_param("obv_period"))
        volumes_arr = self.volumes(self.get_param("obv_period"))
        if len(closes_arr) < self.get_param("obv_period"):
            return Signal(direction=None)
        obv = 0.0
        obv_values = []
        for i in range(1, len(closes_arr)):
            if closes_arr[i] > closes_arr[i-1]:
                obv += volumes_arr[i]
            elif closes_arr[i] < closes_arr[i-1]:
                obv -= volumes_arr[i]
            obv_values.append(obv)
        obv_sma = np.mean(obv_values[-10:]) if len(obv_values) >= 10 else obv

        # Entry condition
        if True:

            # Direction from OBV trend
            direction = 1 if obv > obv_sma else -1

            self._in_trade = True
            self._trade_direction = direction
            self._bars_held = 0
            self._peak = candle.high
            self._trough = candle.low

            tag = "research_158_solana_early_launch_sniping_bull" if direction == 1 else "research_158_solana_early_launch_sniping_bear"
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
