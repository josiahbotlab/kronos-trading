#!/usr/bin/env python3
"""
VWAP Extreme Mean Reversion v2.0
===================================
Source: Clawbot Trading Bot That Did 7,547%... What's the Catch?
Confidence: 85%

Improved with proper VWAP bands and ADX trend filter from research:
- Rolling VWAP with standard deviation bands (like Bollinger on VWAP)
- Entry at ±2σ from VWAP, exit at VWAP return
- ADX < 25 filter: only mean-revert in range-bound markets
- Stochastic %K/%D crossover confirms momentum exhaustion
- Trend SMA as additional directional filter

Transcript: VWAP strategy was noted as potentially overfitting (9 trades/25yr),
so widened parameters for more trades while keeping mean-reversion edge.
Web research: ±2σ bands, stochastic 14/3/3, ADX for trend strength filtering.
"""

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from strategies.templates.base_strategy import BaseStrategy, CandleData, Signal
import numpy as np

log = logging.getLogger(__name__)


# =============================================================================
# Entry gates (added 2026-05-11 after audit — vwap_mean_reversion rolling 14d
# = -$43.85 and regressing; PF 0.80; R:R 0.66 against). These are GATES, not
# tuning — they restrict WHEN the strategy fires, never WHAT it fires.
#
# Audit summary (275 trades, total -$38.81):
#   - shorts:  64 trades, -$27.33 total, 50% WR — no edge → LONGS_ONLY
#   - longs in trending_down regime: 5 of 6 recent big losers → engine-level gate
#   - hours 17/18/19/21 UTC: 70-86% WR; all other hours net -$84.20 → window
#
# Each strategy-level gate has a named module-level constant so a future
# operator can toggle individually without code surgery.
#
# NOTE on the regime gate: moved to execution/live_engine.py on 2026-05-12.
# The strategy used to read regime from data/directional_bias.json (a daily
# 00:05 UTC snapshot, so up to ~24h stale). The engine recomputes regime
# fresh each cycle, so the gate is now in `STRATEGY_BLOCKED_REGIMES_LONG`
# at the top of live_engine.py and fires off the live regime.
# =============================================================================

LONGS_ONLY: bool = True
"""Block all SHORT signals. Shorts had no historical edge (50% WR, -$0.43/trade)."""

ACTIVE_HOURS_UTC: frozenset[int] = frozenset({17, 18, 19, 21})
"""Only fire entries during these UTC hours (per skill-file time-of-day
analysis: 17 @ 85.7% WR, 18 @ 72.7%, 19 @ 72.7%, 21 @ 83.3%). Note hour 20
is intentionally excluded — falls in the 17-21 band but is the WORST hour
overall (-$1.67/trade, 37.5% WR). Set to empty frozenset() to disable."""


class VwapMeanReversion(BaseStrategy):
    name = "vwap_mean_reversion"
    version = "2.0"

    def default_params(self) -> dict:
        return {
            # VWAP with deviation bands
            "vwap_period": 50,
            "vwap_band_std": 1.5,         # ±N std deviations from VWAP (loosened)

            # ADX trend filter (don't mean-revert in trends)
            "use_adx_filter": False,      # disabled by default — too restrictive on 1h
            "adx_period": 14,
            "adx_max": 30,                # loosened from 25

            # Stochastic confirmation
            "stoch_k_period": 14,
            "stoch_d_period": 3,
            "stoch_overbought": 80,
            "stoch_oversold": 20,

            # Backup trend filter
            "use_trend_filter": True,
            "trend_sma_period": 100,

            "min_history": 110,

            # Entry
            "entry_strength": 0.65,

            # Exit
            "stop_loss_pct": 0.8,
            "take_profit_pct": 1.2,
            "vwap_exit": True,            # exit when price returns to VWAP
            "max_hold_bars": 16,
            "cooldown_bars": 4,

            "max_history": 300,
        }

    def on_init(self):
        self._in_trade = False
        self._trade_direction = 0
        self._entry_price = 0.0
        self._bars_held = 0
        self._cooldown = 0
        self._entry_vwap = 0.0

    def _compute_vwap_bands(self, n: int):
        """Rolling VWAP with standard deviation bands.
        Returns (vwap, upper_band, lower_band) or None."""
        if len(self._candle_history) < n:
            return None
        data = self._candle_history[-n:]
        typical_prices = np.array([(c.high + c.low + c.close) / 3 for c in data])
        volumes = np.array([c.volume for c in data])

        cum_vol = np.sum(volumes)
        if cum_vol < 1e-8:
            return None

        vwap = np.sum(typical_prices * volumes) / cum_vol

        # Standard deviation of typical price from VWAP, volume-weighted
        variance = np.sum(volumes * (typical_prices - vwap) ** 2) / cum_vol
        std = np.sqrt(variance)

        band_mult = self.get_param("vwap_band_std")
        return vwap, vwap + band_mult * std, vwap - band_mult * std

    def _compute_adx(self) -> float | None:
        """Simplified ADX calculation for trend strength."""
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

        # EMA smoothing
        alpha = 2 / (period + 1)
        def ema_arr(arr):
            result = np.zeros(len(arr))
            result[0] = arr[0]
            for i in range(1, len(arr)):
                result[i] = alpha * arr[i] + (1 - alpha) * result[i - 1]
            return result

        tr_arr = np.array(tr_list)
        atr = ema_arr(tr_arr)
        smooth_pdm = ema_arr(np.array(plus_dm))
        smooth_ndm = ema_arr(np.array(minus_dm))

        plus_di = 100 * smooth_pdm / np.maximum(atr, 1e-8)
        minus_di = 100 * smooth_ndm / np.maximum(atr, 1e-8)

        di_sum = plus_di + minus_di
        di_diff = np.abs(plus_di - minus_di)
        dx = 100 * di_diff / np.maximum(di_sum, 1e-8)

        adx = ema_arr(dx)
        return float(adx[-1])

    def _compute_stochastic(self) -> tuple[float, float] | None:
        """Stochastic %K and %D."""
        k_period = self.get_param("stoch_k_period")
        d_period = self.get_param("stoch_d_period")
        need = k_period + d_period

        if len(self._candle_history) < need:
            return None

        k_values = []
        for i in range(d_period):
            end = len(self._candle_history) - (d_period - 1 - i)
            start = end - k_period
            if start < 0:
                return None
            window = self._candle_history[start:end]
            highest = max(c.high for c in window)
            lowest = min(c.low for c in window)
            if highest == lowest:
                k_values.append(50.0)
            else:
                close = window[-1].close
                k_values.append(100 * (close - lowest) / (highest - lowest))

        pct_k = k_values[-1]
        pct_d = float(np.mean(k_values))
        return pct_k, pct_d

    def on_candle(self, candle: CandleData) -> Signal:
        if self._cooldown > 0:
            self._cooldown -= 1

        # --- IN POSITION ---
        if self._in_trade:
            self._bars_held += 1

            stop_pct = self.get_param("stop_loss_pct") / 100
            tp_pct = self.get_param("take_profit_pct") / 100

            if self._trade_direction == 1:
                if candle.low <= self._entry_price * (1 - stop_pct):
                    return self._exit("stop_loss")
                if candle.high >= self._entry_price * (1 + tp_pct):
                    return self._exit("take_profit")
            else:
                if candle.high >= self._entry_price * (1 + stop_pct):
                    return self._exit("stop_loss")
                if candle.low <= self._entry_price * (1 - tp_pct):
                    return self._exit("take_profit")

            # Exit when price returns to VWAP
            if self.get_param("vwap_exit"):
                bands = self._compute_vwap_bands(self.get_param("vwap_period"))
                if bands is not None:
                    vwap = bands[0]
                    if self._trade_direction == 1 and candle.close >= vwap:
                        return self._exit("vwap_return")
                    elif self._trade_direction == -1 and candle.close <= vwap:
                        return self._exit("vwap_return")

            if self._bars_held >= self.get_param("max_hold_bars"):
                return self._exit("max_hold")

            return Signal(direction=None)

        # --- NO POSITION ---
        if self._cooldown > 0:
            return Signal(direction=None)

        if len(self._candle_history) < self.get_param("min_history"):
            return Signal(direction=None)

        # Compute VWAP bands
        bands = self._compute_vwap_bands(self.get_param("vwap_period"))
        if bands is None:
            return Signal(direction=None)
        vwap, upper, lower = bands

        # ADX filter: only mean-revert in range-bound markets
        if self.get_param("use_adx_filter"):
            adx_val = self._compute_adx()
            if adx_val is not None and adx_val > self.get_param("adx_max"):
                return Signal(direction=None)

        # Check if price is outside bands
        if candle.close > lower and candle.close < upper:
            return Signal(direction=None)  # inside bands, no signal

        # Stochastic confirmation
        stoch = self._compute_stochastic()
        if stoch is None:
            return Signal(direction=None)
        pct_k, pct_d = stoch

        # Trend filter: avoid mean-reverting against strong macro trend
        if self.get_param("use_trend_filter"):
            trend_sma = self.sma(self.get_param("trend_sma_period"))
            if trend_sma is not None:
                if candle.close < lower and candle.close < trend_sma * 0.97:
                    return Signal(direction=None)
                if candle.close > upper and candle.close > trend_sma * 1.03:
                    return Signal(direction=None)

        direction = None
        # Price below lower band + stochastic oversold → long
        if candle.close <= lower and pct_k < self.get_param("stoch_oversold"):
            direction = 1
        # Price above upper band + stochastic overbought → short
        elif candle.close >= upper and pct_k > self.get_param("stoch_overbought"):
            direction = -1

        if direction is None:
            return Signal(direction=None)

        # ───────────────────────────────────────────────────────────────────
        # ENTRY GATES (audit fix 2026-05-11; regime gate moved to engine on
        # 2026-05-12). Order: cheapest check first. All gates return
        # Signal(direction=None) → no entry, no state change.
        # The third gate (regime block on LONG in trending_down) lives in
        # execution/live_engine.py::STRATEGY_BLOCKED_REGIMES_LONG so it can
        # use the engine's freshly-computed regime instead of the stale
        # bias-file snapshot.
        # ───────────────────────────────────────────────────────────────────

        # Gate 1: LONGS_ONLY — shorts had no historical edge.
        if LONGS_ONLY and direction == -1:
            log.info(
                "[GATE] vwap_mean_reversion: SHORT blocked (LONGS_ONLY)"
            )
            return Signal(direction=None, tag="gate_longs_only")

        # Gate 3: time-of-day window. Use the CANDLE's timestamp, not wall
        # clock, so backtests and live see identical behaviour.
        if ACTIVE_HOURS_UTC:
            bar_hour = datetime.fromtimestamp(
                candle.timestamp_ms / 1000, tz=timezone.utc
            ).hour
            if bar_hour not in ACTIVE_HOURS_UTC:
                log.debug(
                    "[GATE] vwap_mean_reversion: hour %d UTC not in active "
                    "window %s — skipping", bar_hour, sorted(ACTIVE_HOURS_UTC)
                )
                return Signal(direction=None, tag="gate_active_hours")

        self._in_trade = True
        self._trade_direction = direction
        self._entry_price = candle.close
        self._entry_vwap = vwap
        self._bars_held = 0

        dev_pct = (candle.close - vwap) / vwap * 100

        return Signal(
            direction=direction,
            strength=self.get_param("entry_strength"),
            tag=f"vwap_rev_{'long' if direction == 1 else 'short'}",
            metadata={"vwap": vwap, "deviation_pct": dev_pct, "stoch_k": pct_k},
        )

    def _exit(self, reason: str) -> Signal:
        self._in_trade = False
        self._trade_direction = 0
        self._cooldown = self.get_param("cooldown_bars")
        return Signal(direction=0, tag=f"exit_{reason}")

    def on_trade(self, pnl: float, pnl_pct: float):
        self._in_trade = False
        self._trade_direction = 0


PARAM_RANGES = {
    "vwap_period": [30, 50, 75, 100],
    "vwap_band_std": [1.5, 2.0, 2.5],
    "adx_max": [20, 25, 30],
    "stoch_k_period": [10, 14, 20],
    "stoch_overbought": [75, 80, 85],
    "stoch_oversold": [15, 20, 25],
    "stop_loss_pct": [0.5, 0.8, 1.2],
    "take_profit_pct": [0.8, 1.2, 1.8],
    "max_hold_bars": [12, 16, 20],
}
