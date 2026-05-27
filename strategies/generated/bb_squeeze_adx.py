#!/usr/bin/env python3
"""
Bollinger Band Squeeze Breakout with ADX (Hand-Coded)
======================================================
Research ID: 163
Category: breakout
Source: Moon Dev

BB squeeze inside Keltner Channels = low volatility consolidation.
When price breaks out, ADX confirms trend strength.
Targets ~20% time in market to reduce black swan risk.

Moon Dev params: BB(20,2), Keltner(20,1.5 ATR), ADX optimized,
SL 2-4%, expectancy >0.2, Sharpe >1.2, PF >1.08, WR 40-57%.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from strategies.templates.base_strategy import BaseStrategy, CandleData, Signal
import numpy as np


class BBSqueezeADX(BaseStrategy):
    name = "bb_squeeze_adx"
    version = "1.0"

    def default_params(self) -> dict:
        return {
            # Bollinger Bands
            "bb_period": 20,
            "bb_std": 2.0,

            # Keltner Channels
            "kc_period": 20,
            "kc_atr_mult": 1.5,

            # ADX
            "adx_period": 14,
            "adx_threshold": 20,   # Min ADX to confirm breakout

            # Squeeze detection
            "squeeze_min_bars": 3,  # Min bars in squeeze before breakout counts

            # Exit management
            "take_profit_pct": 3.0,
            "stop_loss_pct": 2.5,   # Moon Dev: 2-4%, midpoint
            "max_hold_bars": 60,

            # Cooldown
            "cooldown_bars": 10,

            "max_history": 500,
            "entry_strength": 0.8,
        }

    def on_init(self):
        self._in_trade = False
        self._trade_direction = 0
        self._bars_held = 0
        self._entry_price = 0.0
        self._cooldown = 0
        self._squeeze_count = 0  # consecutive bars in squeeze

    def _keltner_channels(self) -> tuple[float, float, float] | None:
        """Calculate Keltner Channels: (upper, middle, lower)."""
        period = self.get_param("kc_period")
        atr_val = self.atr(period)
        mid = self.sma(period)
        if atr_val is None or mid is None:
            return None
        mult = self.get_param("kc_atr_mult")
        return (mid + mult * atr_val, mid, mid - mult * atr_val)

    def _calculate_adx(self, period: int) -> float | None:
        """Calculate ADX."""
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
        if di_sum == 0:
            return 0.0

        return float(100 * abs(plus_di - minus_di) / di_sum)

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

        if len(self._candle_history) < self.get_param("bb_period") * 2:
            return Signal(direction=None)

        # Calculate BB and KC
        bb = self.bollinger_bands(self.get_param("bb_period"), self.get_param("bb_std"))
        kc = self._keltner_channels()
        if bb is None or kc is None:
            return Signal(direction=None)

        bb_upper, bb_mid, bb_lower = bb
        kc_upper, kc_mid, kc_lower = kc

        # Squeeze: BB inside KC
        in_squeeze = (bb_upper < kc_upper) and (bb_lower > kc_lower)

        if in_squeeze:
            self._squeeze_count += 1
            return Signal(direction=None)  # Wait for breakout

        # Not in squeeze — check if we JUST exited one
        if self._squeeze_count < self.get_param("squeeze_min_bars"):
            self._squeeze_count = 0
            return Signal(direction=None)

        # Squeeze just ended! This is a breakout candle.
        self._squeeze_count = 0

        # ADX confirmation
        adx = self._calculate_adx(self.get_param("adx_period"))
        if adx is None or adx < self.get_param("adx_threshold"):
            return Signal(direction=None)

        # Direction from breakout: above BB mid = long, below = short
        if candle.close > bb_mid:
            direction = 1
        elif candle.close < bb_mid:
            direction = -1
        else:
            return Signal(direction=None)

        # Enter trade
        self._in_trade = True
        self._trade_direction = direction
        self._bars_held = 0
        self._entry_price = candle.close

        tag = f"bb_squeeze_adx_{'bull' if direction == 1 else 'bear'}"
        return Signal(direction=direction, strength=self.get_param("entry_strength"), tag=tag)

    def _exit(self, reason: str) -> Signal:
        self._in_trade = False
        self._trade_direction = 0
        self._cooldown = self.get_param("cooldown_bars")
        return Signal(direction=0, tag=f"exit_{reason}")

    def on_trade(self, pnl: float, pnl_pct: float):
        self._in_trade = False
        self._trade_direction = 0
