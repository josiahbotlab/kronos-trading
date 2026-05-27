#!/usr/bin/env python3
"""
Liquidation Mean Reversion with ADX Filter (Hand-Coded)
========================================================
Research ID: 34
Category: mean_reversion
Source: Moon Dev — "trading liquidations for cascades or mean reversion"

Core idea: Large long liquidations = capitulation = bottom → go long.
Short liquidation spike after entry = euphoria = top → exit.
ADX filters out low-trend-strength conditions.

Moon Dev claims: 77-103% return vs 50% buy-and-hold, Sharpe 1.24,
24-minute liquidation window, ~11% exposure time.

Hand-coded with actual parameters from research DB + transcript context.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from strategies.templates.base_strategy import BaseStrategy, CandleData, Signal
import numpy as np


class LiqMeanRevADX(BaseStrategy):
    name = "liq_mean_rev_adx"
    version = "1.0"

    def default_params(self) -> dict:
        return {
            # Liquidation detection
            "liq_window": 5,          # 5 bars of 5m = 25 min (~24-min window Moon Dev uses)
            "liq_threshold_pct": 90,  # percentile for "large" liquidation event
            "liq_exit_threshold_pct": 85,  # percentile for exit signal (opposing liq spike)

            # ADX filter
            "adx_period": 14,
            "adx_min": 20,            # Minimum ADX for trend strength confirmation

            # Exit management
            "take_profit_pct": 3.0,   # Moon Dev tested 2-10%, start conservative
            "stop_loss_pct": 2.0,     # Moon Dev tested 2-5%
            "max_hold_bars": 60,      # 5 hours on 5m

            # Anti-flip and cooldown
            "cooldown_bars": 10,      # Don't immediately re-enter after exit
            "anti_flip_bars": 20,     # Don't flip direction for 20 bars (100 min)

            "max_history": 500,
            "entry_strength": 0.8,
        }

    def on_init(self):
        self._in_trade = False
        self._trade_direction = 0
        self._bars_held = 0
        self._entry_price = 0.0
        self._cooldown = 0
        self._last_exit_direction = 0
        self._bars_since_exit = 999

    def _calculate_adx(self, period: int) -> float | None:
        """Calculate ADX from candle history."""
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

            # True Range
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            tr_list.append(tr)

            # Directional Movement
            up_move = high - prev_high
            down_move = prev_low - low

            plus_dm = up_move if (up_move > down_move and up_move > 0) else 0
            minus_dm = down_move if (down_move > up_move and down_move > 0) else 0
            plus_dm_list.append(plus_dm)
            minus_dm_list.append(minus_dm)

        # Smoothed averages (Wilder's smoothing)
        atr = np.mean(tr_list[-period:])
        if atr == 0:
            return None

        plus_di = 100 * np.mean(plus_dm_list[-period:]) / atr
        minus_di = 100 * np.mean(minus_dm_list[-period:]) / atr

        di_sum = plus_di + minus_di
        if di_sum == 0:
            return 0.0

        dx = 100 * abs(plus_di - minus_di) / di_sum

        return float(dx)

    def _liq_sum(self, n_bars: int) -> float:
        """Sum liquidation USD over last n bars."""
        if len(self._candle_history) < n_bars:
            return 0.0
        return sum(c.liquidation_usd for c in self._candle_history[-n_bars:])

    def _long_liq_sum(self, n_bars: int) -> float:
        """Sum LONG liquidations (longs getting rekt) over last n bars."""
        if len(self._candle_history) < n_bars:
            return 0.0
        return sum(c.long_liq_usd for c in self._candle_history[-n_bars:])

    def _short_liq_sum(self, n_bars: int) -> float:
        """Sum SHORT liquidations (shorts getting rekt) over last n bars."""
        if len(self._candle_history) < n_bars:
            return 0.0
        return sum(c.short_liq_usd for c in self._candle_history[-n_bars:])

    def on_candle(self, candle: CandleData) -> Signal:
        if self._cooldown > 0:
            self._cooldown -= 1
        self._bars_since_exit += 1

        # --- IN POSITION: manage exits ---
        if self._in_trade:
            self._bars_held += 1
            price = candle.close

            # Take profit
            if self._trade_direction == 1:
                tp_price = self._entry_price * (1 + self.get_param("take_profit_pct") / 100)
                sl_price = self._entry_price * (1 - self.get_param("stop_loss_pct") / 100)
                if candle.high >= tp_price:
                    return self._exit("take_profit", 1)
                if candle.low <= sl_price:
                    return self._exit("stop_loss", 1)
            else:
                tp_price = self._entry_price * (1 - self.get_param("take_profit_pct") / 100)
                sl_price = self._entry_price * (1 + self.get_param("stop_loss_pct") / 100)
                if candle.low <= tp_price:
                    return self._exit("take_profit", -1)
                if candle.high >= sl_price:
                    return self._exit("stop_loss", -1)

            # Opposing liquidation spike exit (Moon Dev's exit signal)
            window = self.get_param("liq_window")
            liq_values = self.liq_usd(200)
            nonzero = liq_values[liq_values > 0]
            if len(nonzero) >= 20:
                exit_thresh = np.percentile(nonzero, self.get_param("liq_exit_threshold_pct"))

                if self._trade_direction == 1:
                    # In long: exit if shorts getting liquidated (euphoria/top)
                    short_liq = self._short_liq_sum(window)
                    if short_liq >= exit_thresh:
                        return self._exit("opposing_liq_spike", 1)
                else:
                    # In short: exit if longs getting liquidated (capitulation/bottom)
                    long_liq = self._long_liq_sum(window)
                    if long_liq >= exit_thresh:
                        return self._exit("opposing_liq_spike", -1)

            # Max hold
            if self._bars_held >= self.get_param("max_hold_bars"):
                return self._exit("max_hold", self._trade_direction)

            return Signal(direction=None)

        # --- NO POSITION: check for entry ---
        if self._cooldown > 0:
            return Signal(direction=None)

        if len(self._candle_history) < self.get_param("max_history") // 2:
            return Signal(direction=None)

        # ADX filter — need minimum trend strength
        adx = self._calculate_adx(self.get_param("adx_period"))
        if adx is None or adx < self.get_param("adx_min"):
            return Signal(direction=None)

        # Liquidation accumulation over window
        window = self.get_param("liq_window")
        liq_values = self.liq_usd(200)
        nonzero = liq_values[liq_values > 0]
        if len(nonzero) < 20:
            return Signal(direction=None)

        threshold = np.percentile(nonzero, self.get_param("liq_threshold_pct"))

        long_liq = self._long_liq_sum(window)
        short_liq = self._short_liq_sum(window)

        direction = 0

        # Large long liquidations = capitulation = go LONG (contrarian)
        if long_liq >= threshold:
            direction = 1

        # Large short liquidations = euphoria = go SHORT (contrarian)
        elif short_liq >= threshold:
            direction = -1

        if direction == 0:
            return Signal(direction=None)

        # Anti-flip: don't immediately reverse direction
        if (direction == -self._last_exit_direction and
                self._bars_since_exit < self.get_param("anti_flip_bars")):
            return Signal(direction=None)

        # Enter trade
        self._in_trade = True
        self._trade_direction = direction
        self._bars_held = 0
        self._entry_price = candle.close

        tag = f"liq_mean_rev_adx_{'bull' if direction == 1 else 'bear'}"
        return Signal(
            direction=direction,
            strength=self.get_param("entry_strength"),
            tag=tag,
        )

    def _exit(self, reason: str, direction: int) -> Signal:
        self._in_trade = False
        self._last_exit_direction = direction
        self._trade_direction = 0
        self._bars_since_exit = 0
        self._cooldown = self.get_param("cooldown_bars")
        return Signal(direction=0, tag=f"exit_{reason}")

    def on_trade(self, pnl: float, pnl_pct: float):
        self._in_trade = False
        self._trade_direction = 0
