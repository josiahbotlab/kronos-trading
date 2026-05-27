#!/usr/bin/env python3
"""
Multi-Timeframe Mean Reversion v1.0
====================================
Source: Research DB #291 — Mean Reversion Multi-Timeframe
Confidence: 80%

Uses higher-timeframe trend (4h SMA) to determine direction, 15m SMA as
the mean to revert to, and 5m candles for entry confirmation. Aggregates
5m candles to compute higher-timeframe indicators without separate data feeds.

v1.1: Added Kronos regime gate — rejects longs in trending_down,
      rejects shorts in trending_up. Ranging allows both directions.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from strategies.templates.base_strategy import BaseStrategy, CandleData, Signal
import numpy as np
import logging

from execution.regime_detector import detect_regime

_log = logging.getLogger("strategy.mtf_mean_reversion")


class MtfMeanReversion(BaseStrategy):
    """Multi-timeframe mean reversion: 4h trend, 15m mean, 5m entry."""

    name = "mtf_mean_reversion"
    version = "1.1"

    def default_params(self) -> dict:
        return {
            "htf_sma_period": 20,         # SMA period on 4h (applied to aggregated bars)
            "htf_bars": 48,               # 5m candles per 4h bar
            "mtf_sma_period": 20,         # SMA period on 15m (applied to aggregated bars)
            "mtf_bars": 3,                # 5m candles per 15m bar
            "stop_loss_pct": 1.2,
            "take_profit_pct": 1.2,
            "max_hold_bars": 24,
            "cooldown_bars": 5,
            "entry_strength": 0.7,
            "min_history": 200,           # Need enough for 4h SMA: 50 * 48 = 2400 ideal, but 300 is workable
            "max_history": 2500,
        }

    def on_init(self):
        self._in_trade = False
        self._trade_dir = 0
        self._entry_price = 0.0
        self._bars_held = 0
        self._cooldown = 0
        self._diag_count = 0

    def _aggregate_closes(self, bar_size: int, count: int) -> np.ndarray | None:
        """Aggregate 5m candles into higher-timeframe closes.
        bar_size: number of 5m candles per HTF bar
        count: how many HTF bars we need
        """
        need = bar_size * count
        if len(self._candle_history) < need:
            return None
        candles = self._candle_history[-need:]
        closes = []
        for i in range(0, len(candles), bar_size):
            chunk = candles[i:i + bar_size]
            if len(chunk) == bar_size:
                closes.append(chunk[-1].close)  # Use last close of the period
        return np.array(closes) if closes else None

    def _htf_trend(self) -> int | None:
        """Determine 4h trend direction using SMA.
        Returns 1 (bullish), -1 (bearish), or None."""
        period = self.get_param("htf_sma_period")
        bar_size = self.get_param("htf_bars")
        closes = self._aggregate_closes(bar_size, period + 1)
        if closes is None or len(closes) < period:
            return None
        sma_val = float(np.mean(closes[-period:]))
        current = closes[-1]
        if current > sma_val:
            return 1
        elif current < sma_val:
            return -1
        return None

    def _mtf_sma(self) -> float | None:
        """Compute 15m SMA from aggregated 5m candles."""
        period = self.get_param("mtf_sma_period")
        bar_size = self.get_param("mtf_bars")
        closes = self._aggregate_closes(bar_size, period + 1)
        if closes is None or len(closes) < period:
            return None
        return float(np.mean(closes[-period:]))

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

        # Compute multi-timeframe indicators
        htf_dir = self._htf_trend()
        mtf_sma = self._mtf_sma()

        if htf_dir is None or mtf_sma is None:
            return Signal(direction=None)

        # 5m confirmation: last candle direction
        if len(self._candle_history) < 2:
            return Signal(direction=None)
        prev = self._candle_history[-2]
        candle_green = candle.close > candle.open
        candle_red = candle.close < candle.open

        # Diagnostic logging every 12 candles
        if self._diag_count % 12 == 0:
            _log.info(
                f"DIAG #{self._diag_count}: close={candle.close:.0f} "
                f"htf_trend={htf_dir} mtf_sma={mtf_sma:.0f} "
                f"below_sma={candle.close < mtf_sma} "
                f"candle_green={candle_green} candle_red={candle_red}"
            )

        # Entry logic
        entry_signal = 0

        # Long: 4h bullish + price below 15m SMA + 5m green candle
        if htf_dir == 1 and candle.close < mtf_sma and candle_green:
            entry_signal = 1

        # Short: 4h bearish + price above 15m SMA + 5m red candle
        if htf_dir == -1 and candle.close > mtf_sma and candle_red:
            entry_signal = -1

        if entry_signal == 0:
            return Signal(direction=None)

        # --- Kronos regime gate: don't fight the macro trend ---
        regime = detect_regime(self._candle_history)
        if entry_signal == 1 and regime == "trending_down":
            _log.info(
                f"mtf_mean_reversion: LONG rejected (regime={regime}) "
                f"close={candle.close:.0f} htf_trend={htf_dir}"
            )
            return Signal(direction=None)
        if entry_signal == -1 and regime == "trending_up":
            _log.info(
                f"mtf_mean_reversion: SHORT rejected (regime={regime}) "
                f"close={candle.close:.0f} htf_trend={htf_dir}"
            )
            return Signal(direction=None)

        _log.info(
            f"ENTRY DETECTED: dir={entry_signal} close={candle.close:.0f} "
            f"htf_trend={htf_dir} mtf_sma={mtf_sma:.0f} regime={regime}"
        )

        self._in_trade = True
        self._trade_dir = entry_signal
        self._entry_price = candle.close
        self._bars_held = 0

        return Signal(
            direction=entry_signal,
            strength=self.get_param("entry_strength"),
            tag=f"{'long' if entry_signal == 1 else 'short'}_mtf_revert",
        )

    def _manage_position(self, candle: CandleData) -> Signal:
        sl_pct = self.get_param("stop_loss_pct") / 100
        tp_pct = self.get_param("take_profit_pct") / 100

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

        if self._bars_held >= self.get_param("max_hold_bars"):
            return self._exit("max_hold")

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
    "htf_sma_period": [30, 50, 70],
    "mtf_sma_period": [15, 20, 30],
    "stop_loss_pct": [0.8, 1.2, 1.8],
    "take_profit_pct": [0.8, 1.2, 1.8],
    "max_hold_bars": [16, 24, 32],
}
