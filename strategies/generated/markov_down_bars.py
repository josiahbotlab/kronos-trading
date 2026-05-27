#!/usr/bin/env python3
"""
Markov Consecutive Down Bars Mean Reversion (Hand-Coded)
========================================================
Source: Moon Dev — Jim Simons Markov model research session (503AYeIsiWA)

After N consecutive down bars (close < prior close), go long.
66% probability of reversal after 5-6 consecutive down bars.
Exit when close > prior close (up bar) or TP/SL hit.

Adapted from daily SPY to 5m BTC.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from strategies.templates.base_strategy import BaseStrategy, CandleData, Signal
import numpy as np


class MarkovDownBars(BaseStrategy):
    name = "markov_down_bars"
    version = "1.0"

    def default_params(self) -> dict:
        return {
            # Consecutive down bars required
            "consec_down_bars": 5,     # Moon Dev: 5-6 on daily. 5 on 5m.

            # Also trade shorts on consecutive up bars
            "consec_up_bars": 5,

            # Exit on reversal bar
            "exit_on_reversal": True,  # Moon Dev: exit when next bar closes up

            # Exit management
            "take_profit_pct": 1.5,
            "stop_loss_pct": 1.0,
            "max_hold_bars": 24,       # 2 hours

            # Cooldown
            "cooldown_bars": 6,

            "max_history": 500,
            "entry_strength": 0.8,
        }

    def on_init(self):
        self._in_trade = False
        self._trade_direction = 0
        self._bars_held = 0
        self._entry_price = 0.0
        self._cooldown = 0

    def _count_consecutive_down(self) -> int:
        """Count consecutive bars where close < prior close."""
        count = 0
        candles = self._candle_history
        for i in range(len(candles) - 1, 0, -1):
            if candles[i].close < candles[i - 1].close:
                count += 1
            else:
                break
        return count

    def _count_consecutive_up(self) -> int:
        """Count consecutive bars where close > prior close."""
        count = 0
        candles = self._candle_history
        for i in range(len(candles) - 1, 0, -1):
            if candles[i].close > candles[i - 1].close:
                count += 1
            else:
                break
        return count

    def on_candle(self, candle: CandleData) -> Signal:
        if self._cooldown > 0:
            self._cooldown -= 1

        # --- IN POSITION ---
        if self._in_trade:
            self._bars_held += 1

            # Reversal bar exit
            if self.get_param("exit_on_reversal") and len(self._candle_history) >= 2:
                prev = self._candle_history[-2].close
                if self._trade_direction == 1 and candle.close > prev:
                    return self._exit("reversal_bar")
                if self._trade_direction == -1 and candle.close < prev:
                    return self._exit("reversal_bar")

            # TP/SL
            if self._trade_direction == 1:
                tp = self._entry_price * (1 + self.get_param("take_profit_pct") / 100)
                sl = self._entry_price * (1 - self.get_param("stop_loss_pct") / 100)
                if candle.high >= tp:
                    return self._exit("take_profit")
                if candle.low <= sl:
                    return self._exit("stop_loss")
            else:
                tp = self._entry_price * (1 - self.get_param("take_profit_pct") / 100)
                sl = self._entry_price * (1 + self.get_param("stop_loss_pct") / 100)
                if candle.low <= tp:
                    return self._exit("take_profit")
                if candle.high >= sl:
                    return self._exit("stop_loss")

            if self._bars_held >= self.get_param("max_hold_bars"):
                return self._exit("max_hold")
            return Signal(direction=None)

        # --- NO POSITION ---
        if self._cooldown > 0:
            return Signal(direction=None)

        if len(self._candle_history) < self.get_param("consec_down_bars") + 2:
            return Signal(direction=None)

        direction = 0

        # Check consecutive down bars → long
        down_count = self._count_consecutive_down()
        if down_count >= self.get_param("consec_down_bars"):
            direction = 1

        # Check consecutive up bars → short
        if direction == 0:
            up_count = self._count_consecutive_up()
            if up_count >= self.get_param("consec_up_bars"):
                direction = -1

        if direction == 0:
            return Signal(direction=None)

        # Enter trade
        self._in_trade = True
        self._trade_direction = direction
        self._bars_held = 0
        self._entry_price = candle.close

        tag = f"markov_{'long' if direction == 1 else 'short'}_{down_count if direction == 1 else up_count}bars"
        return Signal(direction=direction, strength=self.get_param("entry_strength"), tag=tag)

    def _exit(self, reason: str) -> Signal:
        self._in_trade = False
        self._trade_direction = 0
        self._cooldown = self.get_param("cooldown_bars")
        return Signal(direction=0, tag=f"exit_{reason}")

    def on_trade(self, pnl: float, pnl_pct: float):
        self._in_trade = False
        self._trade_direction = 0
