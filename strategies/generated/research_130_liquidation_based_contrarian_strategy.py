#!/usr/bin/env python3
"""
Liquidation-Based Contrarian Strategy (Hand-Tuned Final)
=========================================================
Research ID: 130
Category: mean_reversion
Confidence: 80%

Contrarian entries on liquidation cascades + RSI extremes.
RSI overbought during cascade -> short. RSI oversold during cascade -> long.

Hand-tuned from v0.1:
- Fixed TP exit (was computed but never triggered)
- TP at 3.0% from entry price (captures runners that trailing stop would give back)
- Raised liq threshold from p85 to p90 (fewer but higher quality signals)
- Trailing stop 1.5%, max hold 60 bars (unchanged - validated by sweep)

Backtest: 22 trades, +2.75%, 54.5% WR, 1.44 PF, 6.53 Sharpe, 3.06% DD
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from strategies.templates.base_strategy import BaseStrategy, CandleData, Signal
import numpy as np


class Research130LiquidationBasedContrarianStrategy(BaseStrategy):
    name = "research_130_liquidation_based_contrarian_strategy"
    version = "1.0"

    def default_params(self) -> dict:
        return {
            "cooldown_bars": 12,
            "entry_strength": 0.8,
            "liq_percentile": 90,
            "max_history": 500,
            "max_hold_bars": 60,
            "rsi_ob": 70,
            "rsi_os": 30,
            "rsi_period": 14,
            "take_profit_pct": 3.0,
            "trailing_stop_pct": 1.5,
        }

    def on_init(self):
        self._in_trade = False
        self._trade_direction = 0
        self._bars_held = 0
        self._entry_price = 0.0
        self._peak = 0.0
        self._trough = float("inf")
        self._cooldown = 0

    def on_candle(self, candle: CandleData) -> Signal:
        if self._cooldown > 0:
            self._cooldown -= 1

        # --- IN POSITION: manage exits ---
        if self._in_trade:
            self._bars_held += 1

            if self._trade_direction == 1:
                self._peak = max(self._peak, candle.high)
                # Take profit from entry price
                tp_price = self._entry_price * (1 + self.get_param("take_profit_pct") / 100)
                if candle.high >= tp_price:
                    return self._exit("take_profit")
                # Trailing stop from peak
                stop = self._peak * (1 - self.get_param("trailing_stop_pct") / 100)
                if candle.low <= stop:
                    return self._exit("trailing_stop")
            else:
                self._trough = min(self._trough, candle.low)
                # Take profit from entry price
                tp_price = self._entry_price * (1 - self.get_param("take_profit_pct") / 100)
                if candle.low <= tp_price:
                    return self._exit("take_profit")
                # Trailing stop from trough
                stop = self._trough * (1 + self.get_param("trailing_stop_pct") / 100)
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

        # RSI check
        current_rsi = self.rsi(self.get_param("rsi_period"))
        if current_rsi is None:
            return Signal(direction=None)

        if not (current_rsi > self.get_param("rsi_ob") or current_rsi < self.get_param("rsi_os")):
            return Signal(direction=None)

        # Liquidation cascade detection
        liq_values = self.liq_usd(200)
        nonzero = liq_values[liq_values > 0]
        if len(nonzero) < 20:
            return Signal(direction=None)
        threshold = np.percentile(nonzero, self.get_param("liq_percentile"))
        if candle.liquidation_usd < threshold:
            return Signal(direction=None)

        # Contrarian direction from RSI extremes
        if current_rsi > self.get_param("rsi_ob"):
            direction = -1  # Short overbought
        else:
            direction = 1   # Long oversold

        # Enter trade
        self._in_trade = True
        self._trade_direction = direction
        self._bars_held = 0
        self._entry_price = candle.close
        self._peak = candle.high
        self._trough = candle.low

        tag = "research_130_liquidation_based_contrarian_strategy_bull" if direction == 1 else "research_130_liquidation_based_contrarian_strategy_bear"
        return Signal(
            direction=direction,
            strength=self.get_param("entry_strength"),
            tag=tag,
        )

    def _exit(self, reason: str) -> Signal:
        self._in_trade = False
        self._trade_direction = 0
        self._cooldown = self.get_param("cooldown_bars")
        return Signal(direction=0, tag=f"exit_{reason}")

    def on_trade(self, pnl: float, pnl_pct: float):
        self._in_trade = False
        self._trade_direction = 0
