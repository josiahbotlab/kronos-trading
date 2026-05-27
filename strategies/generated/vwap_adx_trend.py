#!/usr/bin/env python3
"""
VWAP + ADX Trend Following (Hand-Coded)
========================================
Source: Moon Dev — OpenAI O3 backtesting demo (206pD438P9g)

Long when: close > VWAP(20), ADX > 25, +DI > -DI
Short when: close < VWAP(20), ADX > 25, -DI > +DI

Adapted from daily stocks to 5m BTC.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from strategies.templates.base_strategy import BaseStrategy, CandleData, Signal
import numpy as np


class VwapAdxTrend(BaseStrategy):
    name = "vwap_adx_trend"
    version = "1.0"

    def default_params(self) -> dict:
        return {
            # VWAP rolling window
            "vwap_period": 20,

            # ADX
            "adx_period": 14,
            "adx_threshold": 25,   # Moon Dev: ADX > 25

            # Exit management
            "take_profit_pct": 2.0,
            "stop_loss_pct": 1.5,
            "max_hold_bars": 48,   # 4 hours

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

    def _rolling_vwap(self) -> float | None:
        """Calculate rolling VWAP over period bars."""
        period = self.get_param("vwap_period")
        if len(self._candle_history) < period:
            return None

        candles = self._candle_history[-period:]
        cum_tp_vol = 0.0
        cum_vol = 0.0
        for c in candles:
            tp = (c.high + c.low + c.close) / 3
            cum_tp_vol += tp * c.volume
            cum_vol += c.volume

        if cum_vol == 0:
            return None
        return cum_tp_vol / cum_vol

    def _calculate_adx_di(self, period: int) -> tuple[float, float, float] | None:
        """Calculate ADX, +DI, -DI."""
        if len(self._candle_history) < period * 2 + 1:
            return None

        candles = self._candle_history[-(period * 2 + 1):]
        plus_dm_list = []
        minus_dm_list = []
        tr_list = []

        for i in range(1, len(candles)):
            high = candles[i].high
            low = candles[i].low
            prev_high = candles[i - 1].high
            prev_low = candles[i - 1].low
            prev_close = candles[i - 1].close

            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            tr_list.append(tr)

            up_move = high - prev_high
            down_move = prev_low - low
            plus_dm = up_move if (up_move > down_move and up_move > 0) else 0
            minus_dm = down_move if (down_move > up_move and down_move > 0) else 0
            plus_dm_list.append(plus_dm)
            minus_dm_list.append(minus_dm)

        atr_val = np.mean(tr_list[-period:])
        if atr_val == 0:
            return None

        plus_di = 100 * np.mean(plus_dm_list[-period:]) / atr_val
        minus_di = 100 * np.mean(minus_dm_list[-period:]) / atr_val

        di_sum = plus_di + minus_di
        adx = float(100 * abs(plus_di - minus_di) / di_sum) if di_sum > 0 else 0.0
        return (adx, float(plus_di), float(minus_di))

    def on_candle(self, candle: CandleData) -> Signal:
        if self._cooldown > 0:
            self._cooldown -= 1

        # --- IN POSITION ---
        if self._in_trade:
            self._bars_held += 1

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

        if len(self._candle_history) < self.get_param("vwap_period") * 2:
            return Signal(direction=None)

        # VWAP
        vwap = self._rolling_vwap()
        if vwap is None:
            return Signal(direction=None)

        # ADX + DI
        adx_result = self._calculate_adx_di(self.get_param("adx_period"))
        if adx_result is None:
            return Signal(direction=None)

        adx, plus_di, minus_di = adx_result
        if adx < self.get_param("adx_threshold"):
            return Signal(direction=None)

        direction = 0
        if candle.close > vwap and plus_di > minus_di:
            direction = 1   # Long
        elif candle.close < vwap and minus_di > plus_di:
            direction = -1  # Short

        if direction == 0:
            return Signal(direction=None)

        # Enter trade
        self._in_trade = True
        self._trade_direction = direction
        self._bars_held = 0
        self._entry_price = candle.close

        tag = f"vwap_adx_{'bull' if direction == 1 else 'bear'}"
        return Signal(direction=direction, strength=self.get_param("entry_strength"), tag=tag)

    def _exit(self, reason: str) -> Signal:
        self._in_trade = False
        self._trade_direction = 0
        self._cooldown = self.get_param("cooldown_bars")
        return Signal(direction=0, tag=f"exit_{reason}")

    def on_trade(self, pnl: float, pnl_pct: float):
        self._in_trade = False
        self._trade_direction = 0
