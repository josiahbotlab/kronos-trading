#!/usr/bin/env python3
"""
Z-Score Statistical Arbitrage (Hand-Coded)
===========================================
Research ID: 292
Category: mean_reversion
Source: Moon Dev

Multi-period Z-score confirmation (5, 10, 20 bars) with supply/demand zones.
Enter when 2 of 3 Z-scores are oversold at statistical extremes.
Exit on Z-score normalization or profit targets.

Moon Dev params: Z-thresholds [-1.5, -1.35, -1.2], TP 0.45%, SL 0.25%,
zone proximity 0.5, price rank under 10th percentile.

Adapted from 1m to 5m (our backtester timeframe).
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from strategies.templates.base_strategy import BaseStrategy, CandleData, Signal
import numpy as np


class ZScoreStatArb(BaseStrategy):
    name = "zscore_stat_arb"
    version = "1.0"

    def default_params(self) -> dict:
        return {
            # Z-score periods
            "z_period_fast": 5,
            "z_period_mid": 10,
            "z_period_slow": 20,

            # Z-score thresholds (oversold/overbought)
            "z_os_fast": -1.5,    # Z5 oversold
            "z_os_mid": -1.35,    # Z10 oversold
            "z_os_slow": -1.2,    # Z20 oversold
            "z_ob_fast": 1.5,     # Z5 overbought
            "z_ob_mid": 1.35,     # Z10 overbought
            "z_ob_slow": 1.2,     # Z20 overbought

            # Confirmation: need N of 3 z-scores to confirm
            "z_confirm_count": 2,

            # Z-score normalization exit
            "z_exit_threshold": 0.3,  # Exit when z-score returns to near zero

            # Supply/demand zones
            "zone_lookback": 6,       # Moon Dev: 6-bar lookback
            "zone_proximity": 0.5,    # % proximity to zone for entry

            # Exit management (adapted from 1m to 5m — wider targets)
            "take_profit_pct": 0.8,   # Moon Dev 0.45% on 1m, widened for 5m
            "stop_loss_pct": 0.5,     # Moon Dev 0.25% on 1m, widened for 5m
            "max_hold_bars": 24,      # 2 hours

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

    def _zscore(self, period: int) -> float | None:
        """Calculate Z-score of current close vs rolling mean/std."""
        closes = self.closes(period)
        if len(closes) < period:
            return None
        mean = np.mean(closes)
        std = np.std(closes, ddof=1)
        if std == 0:
            return 0.0
        return float((closes[-1] - mean) / std)

    def _demand_zone_top(self) -> float | None:
        """Upper bound of demand zone (lowest low area)."""
        lookback = self.get_param("zone_lookback")
        if len(self._candle_history) < lookback:
            return None
        recent = self._candle_history[-lookback:]
        lowest_low = min(c.low for c in recent)
        lowest_close = min(c.close for c in recent)
        return max(lowest_low, lowest_close)

    def _supply_zone_bottom(self) -> float | None:
        """Lower bound of supply zone (highest high area)."""
        lookback = self.get_param("zone_lookback")
        if len(self._candle_history) < lookback:
            return None
        recent = self._candle_history[-lookback:]
        highest_high = max(c.high for c in recent)
        highest_close = max(c.close for c in recent)
        return min(highest_high, highest_close)

    def on_candle(self, candle: CandleData) -> Signal:
        if self._cooldown > 0:
            self._cooldown -= 1

        # --- IN POSITION ---
        if self._in_trade:
            self._bars_held += 1

            # Z-score normalization exit
            z_fast = self._zscore(self.get_param("z_period_fast"))
            if z_fast is not None:
                if self._trade_direction == 1 and z_fast >= self.get_param("z_exit_threshold"):
                    return self._exit("zscore_normalized")
                if self._trade_direction == -1 and z_fast <= -self.get_param("z_exit_threshold"):
                    return self._exit("zscore_normalized")

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

        if len(self._candle_history) < self.get_param("z_period_slow") + 5:
            return Signal(direction=None)

        # Calculate all 3 Z-scores
        z_fast = self._zscore(self.get_param("z_period_fast"))
        z_mid = self._zscore(self.get_param("z_period_mid"))
        z_slow = self._zscore(self.get_param("z_period_slow"))

        if z_fast is None or z_mid is None or z_slow is None:
            return Signal(direction=None)

        # Count oversold confirmations (LONG signal)
        os_count = sum([
            z_fast <= self.get_param("z_os_fast"),
            z_mid <= self.get_param("z_os_mid"),
            z_slow <= self.get_param("z_os_slow"),
        ])

        # Count overbought confirmations (SHORT signal)
        ob_count = sum([
            z_fast >= self.get_param("z_ob_fast"),
            z_mid >= self.get_param("z_ob_mid"),
            z_slow >= self.get_param("z_ob_slow"),
        ])

        required = self.get_param("z_confirm_count")

        direction = 0
        if os_count >= required:
            # Check proximity to demand zone
            dz_top = self._demand_zone_top()
            if dz_top is not None:
                prox = self.get_param("zone_proximity")
                if candle.close <= dz_top * (1 + prox / 100):
                    direction = 1  # Long at oversold near demand
        elif ob_count >= required:
            # Check proximity to supply zone
            sz_bot = self._supply_zone_bottom()
            if sz_bot is not None:
                prox = self.get_param("zone_proximity")
                if candle.close >= sz_bot * (1 - prox / 100):
                    direction = -1  # Short at overbought near supply

        if direction == 0:
            return Signal(direction=None)

        # Enter trade
        self._in_trade = True
        self._trade_direction = direction
        self._bars_held = 0
        self._entry_price = candle.close

        tag = f"zscore_stat_arb_{'bull' if direction == 1 else 'bear'}"
        return Signal(direction=direction, strength=self.get_param("entry_strength"), tag=tag)

    def _exit(self, reason: str) -> Signal:
        self._in_trade = False
        self._trade_direction = 0
        self._cooldown = self.get_param("cooldown_bars")
        return Signal(direction=0, tag=f"exit_{reason}")

    def on_trade(self, pnl: float, pnl_pct: float):
        self._in_trade = False
        self._trade_direction = 0
