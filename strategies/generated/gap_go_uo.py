#!/usr/bin/env python3
"""
Gap and Go with Ultimate Oscillator (Hand-Coded)
==================================================
Research ID: 165
Category: momentum
Source: Moon Dev — Jim Simons approach of combining multiple alpha factors

Gap up >= 0.5% from previous close, confirmed by Ultimate Oscillator,
ADX trend strength, and MFI (Money Flow Index).

Moon Dev claims: 323,000% return optimized, PF 2.43, Sharpe 1.87,
Sortino 3.32, WR 56%, exposure 32%. TP 5%, SL 2%.

Adapted from 1h to 5m — gaps are calculated from prior bar close.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from strategies.templates.base_strategy import BaseStrategy, CandleData, Signal
import numpy as np


class GapGoUO(BaseStrategy):
    name = "gap_go_uo"
    version = "1.0"

    def default_params(self) -> dict:
        return {
            # Gap detection
            "gap_pct": 0.3,       # Moon Dev: 0.5% on 1h. Tighter on 5m.

            # Ultimate Oscillator (Moon Dev: periods 7, 14, 28)
            "uo_period_fast": 7,
            "uo_period_mid": 14,
            "uo_period_slow": 28,
            "uo_oversold": 30,    # Moon Dev: 25. Relaxed for 5m noise.
            "uo_overbought": 70,

            # ADX
            "adx_period": 14,     # Moon Dev: 30, but 5m needs faster
            "adx_threshold": 20,

            # MFI (Money Flow Index) — approximated via volume + price
            "mfi_period": 14,
            "mfi_oversold": 35,   # Moon Dev: 35

            # Exit management
            "take_profit_pct": 3.0,  # Moon Dev: 5%, tightened for 5m
            "stop_loss_pct": 1.5,    # Moon Dev: 2%, tightened for 5m
            "max_hold_bars": 48,     # 4 hours

            # Cooldown
            "cooldown_bars": 12,

            "max_history": 500,
            "entry_strength": 0.8,
        }

    def on_init(self):
        self._in_trade = False
        self._trade_direction = 0
        self._bars_held = 0
        self._entry_price = 0.0
        self._cooldown = 0

    def _ultimate_oscillator(self) -> float | None:
        """Calculate Ultimate Oscillator with 3 periods."""
        p_fast = self.get_param("uo_period_fast")
        p_mid = self.get_param("uo_period_mid")
        p_slow = self.get_param("uo_period_slow")
        needed = p_slow + 1

        if len(self._candle_history) < needed:
            return None

        candles = self._candle_history[-needed:]

        bp_list = []  # Buying Pressure
        tr_list = []  # True Range

        for i in range(1, len(candles)):
            c = candles[i]
            prev_c = candles[i - 1].close
            bp = c.close - min(c.low, prev_c)
            tr = max(c.high, prev_c) - min(c.low, prev_c)
            bp_list.append(bp)
            tr_list.append(tr)

        bp = np.array(bp_list)
        tr = np.array(tr_list)

        # Avoid division by zero
        tr_fast = np.sum(tr[-p_fast:])
        tr_mid = np.sum(tr[-p_mid:])
        tr_slow = np.sum(tr[-p_slow:])

        if tr_fast == 0 or tr_mid == 0 or tr_slow == 0:
            return None

        avg_fast = np.sum(bp[-p_fast:]) / tr_fast
        avg_mid = np.sum(bp[-p_mid:]) / tr_mid
        avg_slow = np.sum(bp[-p_slow:]) / tr_slow

        # UO = 100 * (4*fast + 2*mid + slow) / 7
        uo = 100 * (4 * avg_fast + 2 * avg_mid + avg_slow) / 7
        return float(uo)

    def _mfi(self) -> float | None:
        """Calculate Money Flow Index."""
        period = self.get_param("mfi_period")
        if len(self._candle_history) < period + 1:
            return None

        candles = self._candle_history[-(period + 1):]

        pos_flow = 0.0
        neg_flow = 0.0

        for i in range(1, len(candles)):
            tp_curr = (candles[i].high + candles[i].low + candles[i].close) / 3
            tp_prev = (candles[i-1].high + candles[i-1].low + candles[i-1].close) / 3
            raw_flow = tp_curr * candles[i].volume

            if tp_curr > tp_prev:
                pos_flow += raw_flow
            elif tp_curr < tp_prev:
                neg_flow += raw_flow

        if neg_flow == 0:
            return 100.0
        money_ratio = pos_flow / neg_flow
        return float(100 - (100 / (1 + money_ratio)))

    def _calculate_adx(self, period: int) -> float | None:
        """Calculate ADX."""
        if len(self._candle_history) < period * 2 + 1:
            return None
        candles = self._candle_history[-(period * 2 + 1):]
        plus_dm, minus_dm, tr_list = [], [], []

        for i in range(1, len(candles)):
            h, l, pc = candles[i].high, candles[i].low, candles[i-1].close
            tr_list.append(max(h - l, abs(h - pc), abs(l - pc)))
            up = h - candles[i-1].high
            down = candles[i-1].low - l
            plus_dm.append(up if (up > down and up > 0) else 0)
            minus_dm.append(down if (down > up and down > 0) else 0)

        atr_val = np.mean(tr_list[-period:])
        if atr_val == 0:
            return None
        pdi = 100 * np.mean(plus_dm[-period:]) / atr_val
        mdi = 100 * np.mean(minus_dm[-period:]) / atr_val
        di_sum = pdi + mdi
        return float(100 * abs(pdi - mdi) / di_sum) if di_sum > 0 else 0.0

    def on_candle(self, candle: CandleData) -> Signal:
        if self._cooldown > 0:
            self._cooldown -= 1

        # --- IN POSITION ---
        if self._in_trade:
            self._bars_held += 1

            if self._trade_direction == 1:
                tp = self._entry_price * (1 + self.get_param("take_profit_pct") / 100)
                sl = self._entry_price * (1 - self.get_param("stop_loss_pct") / 100)
                if candle.high >= tp: return self._exit("take_profit")
                if candle.low <= sl: return self._exit("stop_loss")
            else:
                tp = self._entry_price * (1 - self.get_param("take_profit_pct") / 100)
                sl = self._entry_price * (1 + self.get_param("stop_loss_pct") / 100)
                if candle.low <= tp: return self._exit("take_profit")
                if candle.high >= sl: return self._exit("stop_loss")

            if self._bars_held >= self.get_param("max_hold_bars"):
                return self._exit("max_hold")
            return Signal(direction=None)

        # --- NO POSITION ---
        if self._cooldown > 0:
            return Signal(direction=None)

        if len(self._candle_history) < self.get_param("uo_period_slow") + 5:
            return Signal(direction=None)

        # Gap detection: current open vs previous close
        if len(self._candle_history) < 2:
            return Signal(direction=None)

        prev_close = self._candle_history[-2].close
        gap_pct = (candle.open - prev_close) / prev_close * 100

        gap_thresh = self.get_param("gap_pct")

        direction = 0
        if gap_pct >= gap_thresh:
            direction = 1   # Gap up → long
        elif gap_pct <= -gap_thresh:
            direction = -1  # Gap down → short

        if direction == 0:
            return Signal(direction=None)

        # Ultimate Oscillator confirmation
        uo = self._ultimate_oscillator()
        if uo is None:
            return Signal(direction=None)

        if direction == 1 and uo > self.get_param("uo_overbought"):
            return Signal(direction=None)  # Already overbought, skip
        if direction == -1 and uo < self.get_param("uo_oversold"):
            return Signal(direction=None)  # Already oversold, skip

        # ADX confirmation
        adx = self._calculate_adx(self.get_param("adx_period"))
        if adx is None or adx < self.get_param("adx_threshold"):
            return Signal(direction=None)

        # MFI confirmation
        mfi = self._mfi()
        if mfi is not None:
            if direction == 1 and mfi > 80:
                return Signal(direction=None)  # Overbought, skip gap-up
            if direction == -1 and mfi < 20:
                return Signal(direction=None)  # Oversold, skip gap-down

        # Enter trade
        self._in_trade = True
        self._trade_direction = direction
        self._bars_held = 0
        self._entry_price = candle.close

        tag = f"gap_go_uo_{'bull' if direction == 1 else 'bear'}"
        return Signal(direction=direction, strength=self.get_param("entry_strength"), tag=tag)

    def _exit(self, reason: str) -> Signal:
        self._in_trade = False
        self._trade_direction = 0
        self._cooldown = self.get_param("cooldown_bars")
        return Signal(direction=0, tag=f"exit_{reason}")

    def on_trade(self, pnl: float, pnl_pct: float):
        self._in_trade = False
        self._trade_direction = 0
