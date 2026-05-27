#!/usr/bin/env python3
"""
BB + ADX Trend Breakout v1.0
=============================
Source: Research DB #250 — Intraday Bollinger Bands with ADX
Confidence: 90%

Trend-following breakout strategy that enters when price breaks outside
Bollinger Bands with ADX confirmation of trend strength. Exits on mean
reversion to middle band or trend exhaustion (ADX decline).
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from strategies.templates.base_strategy import BaseStrategy, CandleData, Signal
import numpy as np
import logging

_log = logging.getLogger("strategy.bb_adx_trend_breakout")


class BbAdxTrendBreakout(BaseStrategy):
    """Bollinger Band breakout with ADX trend strength confirmation."""

    name = "bb_adx_trend_breakout"
    version = "1.0"

    def default_params(self) -> dict:
        return {
            "bb_period": 20,
            "bb_std": 2.0,
            "adx_period": 14,
            "adx_entry_min": 30,
            "adx_exit_below": 20,
            "stop_loss_pct": 1.0,
            "take_profit_pct": 2.0,
            "max_hold_bars": 30,
            "cooldown_bars": 5,
            "entry_strength": 0.7,
            "min_history": 60,
            "max_history": 500,
        }

    def on_init(self):
        self._in_trade = False
        self._trade_dir = 0
        self._entry_price = 0.0
        self._bars_held = 0
        self._cooldown = 0
        self._diag_count = 0

    def _compute_adx(self) -> float | None:
        """Compute ADX using Wilder's smoothing."""
        period = self.get_param("adx_period")
        need = period * 3
        if len(self._candle_history) < need:
            return None

        candles = self._candle_history[-need:]
        plus_dm = []
        minus_dm = []
        tr_list = []

        for i in range(1, len(candles)):
            high = candles[i].high
            low = candles[i].low
            prev_high = candles[i - 1].high
            prev_low = candles[i - 1].low
            prev_close = candles[i - 1].close

            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            tr_list.append(tr)

            up = high - prev_high
            down = prev_low - low
            plus_dm.append(up if up > down and up > 0 else 0)
            minus_dm.append(down if down > up and down > 0 else 0)

        alpha = 1 / period
        def wilder_smooth(arr):
            result = np.zeros(len(arr))
            result[0] = arr[0]
            for i in range(1, len(arr)):
                result[i] = alpha * arr[i] + (1 - alpha) * result[i - 1]
            return result

        tr_arr = np.array(tr_list)
        atr_s = wilder_smooth(tr_arr)
        smooth_pdm = wilder_smooth(np.array(plus_dm))
        smooth_ndm = wilder_smooth(np.array(minus_dm))

        plus_di = 100 * smooth_pdm / np.maximum(atr_s, 1e-8)
        minus_di = 100 * smooth_ndm / np.maximum(atr_s, 1e-8)

        di_sum = plus_di + minus_di
        di_diff = np.abs(plus_di - minus_di)
        dx = 100 * di_diff / np.maximum(di_sum, 1e-8)
        adx = wilder_smooth(dx)

        return float(adx[-1])

    def on_candle(self, candle: CandleData) -> Signal:
        if self._cooldown > 0:
            self._cooldown -= 1

        if self._in_trade:
            self._bars_held += 1
            return self._manage_position(candle)

        if self._cooldown > 0:
            return Signal(direction=None)

        if len(self._candle_history) < self.get_param("min_history"):
            return Signal(direction=None)

        self._diag_count += 1

        # Compute indicators
        bb = self.bollinger_bands(
            self.get_param("bb_period"), self.get_param("bb_std"))
        adx_val = self._compute_adx()

        if bb is None or adx_val is None:
            return Signal(direction=None)

        upper, mid, lower = bb
        adx_min = self.get_param("adx_entry_min")

        # Diagnostic logging every 12 candles
        if self._diag_count % 12 == 0:
            _log.info(
                f"DIAG #{self._diag_count}: close={candle.close:.0f} "
                f"bb=[upper={upper:.0f}/mid={mid:.0f}/lower={lower:.0f}] "
                f"adx={adx_val:.1f} adx_min={adx_min}"
            )

        # Entry logic
        entry_signal = 0
        if candle.close > upper and adx_val > adx_min:
            entry_signal = 1  # Long breakout above upper BB
        elif candle.close < lower and adx_val > adx_min:
            entry_signal = -1  # Short breakout below lower BB

        if entry_signal == 0:
            return Signal(direction=None)

        _log.info(
            f"ENTRY DETECTED: dir={entry_signal} close={candle.close:.0f} "
            f"adx={adx_val:.1f} bb_upper={upper:.0f} bb_lower={lower:.0f}"
        )

        self._in_trade = True
        self._trade_dir = entry_signal
        self._entry_price = candle.close
        self._bars_held = 0
        self._bb_mid_at_entry = mid

        return Signal(
            direction=entry_signal,
            strength=self.get_param("entry_strength"),
            tag=f"{'long' if entry_signal == 1 else 'short'}_bb_adx_breakout",
        )

    def _manage_position(self, candle: CandleData) -> Signal:
        sl_pct = self.get_param("stop_loss_pct") / 100
        tp_pct = self.get_param("take_profit_pct") / 100

        # Stop loss / take profit
        if self._trade_dir == 1:
            if candle.low <= self._entry_price * (1 - sl_pct):
                return self._exit("stop_loss")
            if candle.high >= self._entry_price * (1 + tp_pct):
                return self._exit("take_profit")
        else:
            if candle.high >= self._entry_price * (1 + sl_pct):
                return self._exit("stop_loss")
            if candle.low <= self._entry_price * (1 - tp_pct):
                return self._exit("take_profit")

        # Max hold
        if self._bars_held >= self.get_param("max_hold_bars"):
            return self._exit("max_hold")

        # Exit on BB middle band reversion (only after 5+ bars held to let winners run)
        if self._bars_held >= 5:
            bb = self.bollinger_bands(
                self.get_param("bb_period"), self.get_param("bb_std"))
            if bb is not None:
                _, mid, _ = bb
                if self._trade_dir == 1 and candle.close <= mid:
                    return self._exit("bb_mid_revert")
                if self._trade_dir == -1 and candle.close >= mid:
                    return self._exit("bb_mid_revert")

        # Exit on ADX exhaustion
        adx_val = self._compute_adx()
        if adx_val is not None and adx_val < self.get_param("adx_exit_below"):
            return self._exit("adx_exhaustion")

        return Signal(direction=None)

    def _exit(self, reason: str) -> Signal:
        self._in_trade = False
        self._trade_dir = 0
        self._cooldown = self.get_param("cooldown_bars")
        return Signal(direction=0, tag=f"exit_{reason}")

    def on_trade(self, pnl: float, pnl_pct: float):
        self._in_trade = False
        self._trade_dir = 0


PARAM_RANGES = {
    "bb_period": [15, 20, 25],
    "bb_std": [1.5, 2.0, 2.5],
    "adx_entry_min": [20, 25, 30],
    "adx_exit_below": [15, 20],
    "stop_loss_pct": [1.0, 1.5, 2.0],
    "take_profit_pct": [2.0, 3.0, 4.0],
    "max_hold_bars": [20, 30, 40],
}
