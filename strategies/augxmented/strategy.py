"""
Augxmented ICT Strategy — 219-888 Replica (v1.1)
===================================================
12-confluence scoring system trading QQQ on 5m candles.
Entry requires BOS trigger + total weighted score >= threshold.

v1.1 changes:
  - ATR-based tiered take profits (TP1/TP2/TP3) replacing flat 4% TP
  - HTF trend filter: shorts require bearish 1h+4h, longs allow bullish/neutral
  - Minimum score raised to 14

Confluences:
  1. FVG Present          (weight 2)
  2. Inverse FVG          (weight 2)
  3. Order Block           (weight 2)
  4. Breaker Block         (weight 2)
  5. BOS Trigger           (weight 3) — REQUIRED
  6. SMT Divergence        (weight 2)
  7. HTF Structure 1h      (weight 1)
  8. HTF Structure 4h      (weight 2)
  9. Premium/Discount      (weight 1)
  10. Volume Spike         (weight 1)
  11. RSI Divergence       (weight 1)
  12. Session Quality      (weight 1)
"""

from datetime import datetime, timezone, timedelta
from strategies.templates.base_strategy import BaseStrategy, CandleData, Signal
from strategies.augxmented.config import (
    WEIGHTS, MINIMUM_SCORE, BOS_REQUIRED,
    FORBIDDEN_TIMES_ET, BEST_SESSIONS,
    NO_ENTRY_BEFORE_ET, NO_ENTRY_AFTER_ET,
    BOS_SWING_LOOKBACK, SMT_LOOKBACK,
)
from strategies.augxmented.timeframe import aggregate_candles
from strategies.augxmented.confluences.fvg import score_fvg
from strategies.augxmented.confluences.order_blocks import score_ob
from strategies.augxmented.confluences.bos import score_bos
from strategies.augxmented.confluences.smt import score_smt
from strategies.augxmented.confluences.structure import (
    detect_structure, score_htf_structure,
    score_premium_discount, score_volume_momentum,
)
from strategies.augxmented.ml.features import extract_features
from strategies.augxmented.ml.regime_filter import RegimeFilter

# Eastern Time offset (UTC-5, or UTC-4 during DST)
ET_OFFSET = timedelta(hours=-5)


class AugxmentedStrategy(BaseStrategy):
    """
    ICT 219-888 replica strategy.
    Runs on 5m candles, builds multi-TF views internally.
    """

    name = "augxmented"
    version = "1.1"

    def default_params(self) -> dict:
        return {
            'min_score': MINIMUM_SCORE,
            'bos_required': BOS_REQUIRED,
            # ATR-based tiered take profits
            'tp1_atr_mult': 1.0,       # TP1: 1.0x ATR — close 50% of position
            'tp2_atr_mult': 1.8,       # TP2: 1.8x ATR — close 30%
            'tp3_atr_mult': 2.8,       # TP3: 2.8x ATR — close remaining 20%
            'trailing_stop_pct': 1.5,
            'max_hold_bars': 48,       # 48 x 5m = 4 hours
            'cooldown_bars': 6,        # 30 min cooldown after exit
            'min_history': 250,        # ~21 hours of 5m candles
            'max_history': 1000,
            # HTF trend filter
            'htf_filter_shorts': True,  # require bearish HTF for shorts
            # ML regime filter
            'ml_filter_enabled': False,     # disabled by default until model is trained
            'ml_confidence_threshold': 0.65,
        }

    def on_init(self):
        """Reset trade state."""
        self._in_trade = False
        self._trade_direction = 0       # 1=long, -1=short
        self._entry_price = 0.0
        self._entry_atr = 0.0           # ATR at entry for TP levels
        self._peak = 0.0                # peak price for long trailing stop
        self._trough = float('inf')     # trough price for short trailing stop
        self._bars_held = 0
        self._cooldown = 0
        self._tp1_hit = False
        self._tp2_hit = False
        self._remaining_qty = 1.0       # fraction of position remaining (1.0 = full)
        self._spy_candles: list[CandleData] = []  # populated externally or via fetch
        self._regime_filter: RegimeFilter | None = None
        if self.get_param('ml_filter_enabled'):
            self._regime_filter = RegimeFilter()  # loads model from default path
        # Signal dedup — prevent identical signals repeating every bar
        self._last_signal_direction = 0
        self._last_signal_price = 0.0
        self._signal_cooldown = 0  # bars remaining before same signal can fire again

    def on_candle(self, candle: CandleData) -> Signal:
        """
        Process a 5m candle through the 12-confluence scoring system.

        Returns Signal(direction=1|-1) on entry, Signal(direction=0) on exit,
        Signal(direction=None) otherwise.
        """
        # Note: caller (backtester/engine) must call _update_history() before on_candle()
        n = len(self._candle_history)
        min_hist = self.get_param('min_history')

        # Not enough history yet
        if n < min_hist:
            return Signal(direction=None, tag="augx_warmup")

        # Manage cooldowns
        if self._cooldown > 0:
            self._cooldown -= 1
        if self._signal_cooldown > 0:
            self._signal_cooldown -= 1

        # --- Position management ---
        if self._in_trade:
            return self._manage_position(candle)

        # --- Entry logic ---
        # Check session validity
        session = self._check_session(candle.timestamp_ms)
        if session == 'forbidden':
            return Signal(direction=None, tag="augx_forbidden_session")

        # Cooldown active
        if self._cooldown > 0:
            return Signal(direction=None, tag="augx_cooldown")

        # Compute ATR
        current_atr = self.atr(14)
        if current_atr is None or current_atr <= 0:
            return Signal(direction=None, tag="augx_no_atr")

        # --- Run confluence detectors ---
        candles = self._candle_history

        # 1. BOS (entry trigger — check first since it's required)
        bos_scores, bos_direction = score_bos(candles, swing_lookback=BOS_SWING_LOOKBACK)
        if self.get_param('bos_required') and bos_scores['bos_trigger'] == 0:
            return Signal(direction=None, tag="augx_no_bos")

        direction = bos_direction  # trade direction follows BOS

        # --- HTF trend filter (pre-compute, gate shorts) ---
        candles_by_tf = {
            '1h': aggregate_candles(candles, '1h'),
            '4h': aggregate_candles(candles, '4h'),
        }

        if self.get_param('htf_filter_shorts') and direction == -1:
            # Shorts require BOTH 1h and 4h to be bearish
            htf_1h = detect_structure(candles_by_tf.get('1h', []))
            htf_4h = detect_structure(candles_by_tf.get('4h', []))
            if htf_1h['trend'] != 'bearish' or htf_4h['trend'] != 'bearish':
                return Signal(direction=None, tag="augx_htf_filter_short",
                              metadata={'htf_1h': htf_1h['trend'], 'htf_4h': htf_4h['trend']})

        if self.get_param('htf_filter_shorts') and direction == 1:
            # Longs allowed when bullish OR neutral (block only if both bearish)
            htf_1h = detect_structure(candles_by_tf.get('1h', []))
            htf_4h = detect_structure(candles_by_tf.get('4h', []))
            if htf_1h['trend'] == 'bearish' and htf_4h['trend'] == 'bearish':
                return Signal(direction=None, tag="augx_htf_filter_long",
                              metadata={'htf_1h': htf_1h['trend'], 'htf_4h': htf_4h['trend']})

        # 2. FVG
        fvg_scores = score_fvg(candles, direction, current_atr)

        # 3-4. Order Blocks + Breaker Blocks
        ob_scores = score_ob(candles, direction, current_atr)

        # 5. SMT Divergence (only if SPY data available)
        smt_scores = {'smt_divergence': 0}
        if self._spy_candles:
            smt_scores = score_smt(candles, self._spy_candles, lookback=SMT_LOOKBACK)

        # 6-7. HTF Structure scoring (already computed candles_by_tf)
        htf_scores = score_htf_structure(candles_by_tf, direction)

        # 8. Premium / Discount
        pd_scores = score_premium_discount(candles, direction)

        # 9-10. Volume + RSI
        vm_scores = score_volume_momentum(candles, direction)

        # 11. Session quality
        session_score = 1 if session == 'best' else 0

        # --- Compute total weighted score ---
        breakdown = {}
        breakdown.update(bos_scores)
        breakdown.update(fvg_scores)
        breakdown.update(ob_scores)
        breakdown.update(smt_scores)
        breakdown.update(htf_scores)
        breakdown.update(pd_scores)
        breakdown.update(vm_scores)
        breakdown['session_quality'] = session_score

        total_score = sum(
            WEIGHTS.get(k, 0) * v for k, v in breakdown.items()
        )

        # --- Entry decision ---
        min_score = self.get_param('min_score')
        if total_score >= min_score:
            # --- Signal dedup: block same direction + same price within 0.1% for 6 bars (30 min) ---
            if self._signal_cooldown > 0 and direction == self._last_signal_direction:
                price_diff = abs(candle.close - self._last_signal_price)
                if self._last_signal_price > 0 and price_diff / self._last_signal_price < 0.001:
                    return Signal(direction=None, tag="augx_signal_dedup",
                                  metadata={'score': total_score, 'breakdown': breakdown})

            # --- ML regime filter gate ---
            htf_1h_trend = detect_structure(candles_by_tf.get('1h', []))['trend']
            htf_4h_trend = detect_structure(candles_by_tf.get('4h', []))['trend']

            if self._regime_filter and self._regime_filter.is_loaded:
                ml_features = extract_features(
                    candles=candles,
                    direction=direction,
                    current_atr=current_atr,
                    breakdown=breakdown,
                    total_score=total_score,
                    htf_1h_trend=htf_1h_trend,
                    htf_4h_trend=htf_4h_trend,
                    timestamp_ms=candle.timestamp_ms,
                )
                ml_confidence = self._regime_filter.predict_proba(ml_features)
                threshold = self.get_param('ml_confidence_threshold')
                if ml_confidence < threshold:
                    return Signal(direction=None, tag="augx_ml_filtered",
                                  metadata={'score': total_score, 'ml_confidence': ml_confidence,
                                            'breakdown': breakdown})
            else:
                ml_confidence = None

            self._enter_trade(direction, candle, current_atr)
            self._last_signal_direction = direction
            self._last_signal_price = candle.close
            self._signal_cooldown = 6  # 6 bars = 30 min on 5m candles
            strength = min(total_score / 20.0, 1.0)  # normalize to 0-1
            metadata = {
                'score': total_score,
                'breakdown': breakdown,
                'bos_direction': direction,
                'atr': current_atr,
                'session': session,
            }
            if ml_confidence is not None:
                metadata['ml_confidence'] = ml_confidence
            return Signal(
                direction=direction,
                strength=strength,
                tag=f"augx_entry_{'long' if direction == 1 else 'short'}",
                metadata=metadata,
            )

        return Signal(direction=None, tag="augx_no_signal",
                      metadata={'score': total_score, 'breakdown': breakdown})

    def _manage_position(self, candle: CandleData) -> Signal:
        """Manage open position: tiered ATR TPs, trailing stop, max hold."""
        self._bars_held += 1
        d = self._trade_direction
        atr = self._entry_atr

        # Compute ATR-based TP levels from entry price
        tp1_dist = atr * self.get_param('tp1_atr_mult')
        tp2_dist = atr * self.get_param('tp2_atr_mult')
        tp3_dist = atr * self.get_param('tp3_atr_mult')

        if d == 1:
            self._peak = max(self._peak, candle.high)
            trailing_stop = self._peak * (1 - self.get_param('trailing_stop_pct') / 100)

            tp1_price = self._entry_price + tp1_dist
            tp2_price = self._entry_price + tp2_dist
            tp3_price = self._entry_price + tp3_dist

            # Check trailing stop first
            if candle.low <= trailing_stop:
                return self._exit("trailing_stop")

            # Tiered TPs — each hit reduces remaining quantity
            if not self._tp1_hit and candle.high >= tp1_price:
                self._tp1_hit = True
                self._remaining_qty *= 0.50  # close 50%
                # Move stop to breakeven after TP1
                self._peak = max(self._peak, self._entry_price)

            if not self._tp2_hit and candle.high >= tp2_price:
                self._tp2_hit = True
                self._remaining_qty *= 0.60  # close 30% of original (0.50 * 0.60 = 0.30 remaining)

            # TP3 = full exit
            if candle.high >= tp3_price:
                return self._exit("take_profit_tp3")

        elif d == -1:
            self._trough = min(self._trough, candle.low)
            trailing_stop = self._trough * (1 + self.get_param('trailing_stop_pct') / 100)

            tp1_price = self._entry_price - tp1_dist
            tp2_price = self._entry_price - tp2_dist
            tp3_price = self._entry_price - tp3_dist

            # Check trailing stop first
            if candle.high >= trailing_stop:
                return self._exit("trailing_stop")

            # Tiered TPs
            if not self._tp1_hit and candle.low <= tp1_price:
                self._tp1_hit = True
                self._remaining_qty *= 0.50
                self._trough = min(self._trough, self._entry_price)

            if not self._tp2_hit and candle.low <= tp2_price:
                self._tp2_hit = True
                self._remaining_qty *= 0.60

            # TP3 = full exit
            if candle.low <= tp3_price:
                return self._exit("take_profit_tp3")

        # Max hold time
        if self._bars_held >= self.get_param('max_hold_bars'):
            reason = "max_hold"
            if self._tp1_hit:
                reason = "max_hold_post_tp1"
            if self._tp2_hit:
                reason = "max_hold_post_tp2"
            return self._exit(reason)

        return Signal(direction=None, tag="augx_hold")

    def _enter_trade(self, direction: int, candle: CandleData, atr: float):
        """Set trade state on entry."""
        self._in_trade = True
        self._trade_direction = direction
        self._entry_price = candle.close
        self._entry_atr = atr
        self._bars_held = 0
        self._tp1_hit = False
        self._tp2_hit = False
        self._remaining_qty = 1.0
        if direction == 1:
            self._peak = candle.high
            self._trough = float('inf')
        else:
            self._trough = candle.low
            self._peak = 0.0

    def _exit(self, reason: str) -> Signal:
        """Clean exit with cooldown reset."""
        d = self._trade_direction
        remaining = self._remaining_qty
        tp1 = self._tp1_hit
        tp2 = self._tp2_hit
        self._in_trade = False
        self._trade_direction = 0
        self._entry_price = 0.0
        self._entry_atr = 0.0
        self._peak = 0.0
        self._trough = float('inf')
        self._bars_held = 0
        self._tp1_hit = False
        self._tp2_hit = False
        self._remaining_qty = 1.0
        self._cooldown = self.get_param('cooldown_bars')
        return Signal(
            direction=0,
            tag=f"augx_exit_{reason}",
            metadata={
                'exit_reason': reason,
                'prev_direction': d,
                'remaining_qty': remaining,
                'tp1_hit': tp1,
                'tp2_hit': tp2,
            },
        )

    def _check_session(self, timestamp_ms: int) -> str:
        """
        Check if current time is in a valid trading session.

        Returns:
            'forbidden' — no trading allowed
            'best' — prime session
            'normal' — acceptable but not prime
        """
        dt_utc = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
        dt_et = dt_utc + ET_OFFSET
        t = dt_et.strftime('%H:%M')

        # Check forbidden windows
        for start, end in FORBIDDEN_TIMES_ET:
            if start <= t < end:
                return 'forbidden'

        # Check entry time bounds
        if t < NO_ENTRY_BEFORE_ET or t >= NO_ENTRY_AFTER_ET:
            return 'forbidden'

        # Check best sessions
        for start, end in BEST_SESSIONS:
            if start <= t < end:
                return 'best'

        return 'normal'

    def on_trade(self, pnl: float, pnl_pct: float):
        """Called when a trade completes."""
        pass
