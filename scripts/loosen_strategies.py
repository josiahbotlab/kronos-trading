#!/usr/bin/env python3
"""Loosen thresholds on 8 zero-signal strategies to target 2-5 signals/day on 5m BTC."""
import re
from pathlib import Path

BASE = Path.home() / "kronos-trading"

def replace_param(content, param, old_val, new_val, comment_suffix=""):
    """Replace a parameter value in default_params()."""
    # Handle bool, int, float, string
    old_str = str(old_val)
    new_str = str(new_val)
    # Try exact match first
    pattern = f'"{param}": {old_str}'
    replacement = f'"{param}": {new_str}'
    if pattern in content:
        content = content.replace(pattern, replacement, 1)
    else:
        # Try with trailing comma
        pattern = f'"{param}": {old_str},'
        replacement = f'"{param}": {new_str},'
        if pattern in content:
            content = content.replace(pattern, replacement, 1)
    return content

changes = {}

# ── 1. cascade_p99 ──
# P99 → P85, direction 0.6 → 0.55
f = BASE / "strategies/momentum/cascade_p99.py"
c = f.read_text()
c = replace_param(c, "percentile", 99, 85)
c = replace_param(c, "liq_ratio_threshold", 0.6, 0.55)
c = replace_param(c, "min_history", 100, 60)
f.write_text(c)
changes["cascade_p99"] = "P99→P85, direction 0.60→0.55, min_history 100→60"

# ── 2. cascade_ride ──
# Absolute $50K → $5K, direction 0.65 → 0.55, liq_count 3→1, disable confirmation, relax vol filter
f = BASE / "strategies/momentum/cascade_ride.py"
c = f.read_text()
c = replace_param(c, "liq_threshold_usd", 50000, 5000)
c = replace_param(c, "liq_count_min", 3, 1)
c = replace_param(c, "liq_ratio_threshold", 0.65, 0.55)
c = replace_param(c, "use_confirmation", "True", "False")
c = replace_param(c, "min_volume_sma_ratio", 1.2, 1.0)
f.write_text(c)
changes["cascade_ride"] = "liq $50K→$5K, count 3→1, direction 0.65→0.55, no confirm, vol 1.2→1.0"

# ── 3. double_decay_reversal ──
# P90→P80, relax decay ratios (allow less decay), disable RSI extreme requirement, wider wait
f = BASE / "strategies/reversal/double_decay.py"
c = f.read_text()
c = replace_param(c, "cascade_percentile", 90, 80)
c = replace_param(c, "decay_1_ratio", 0.5, 0.7)
c = replace_param(c, "decay_2_ratio", 0.25, 0.5)
c = replace_param(c, "max_wait_bars", 5, 8)
c = replace_param(c, "require_rsi_extreme", "True", "False")
c = replace_param(c, "liq_direction_threshold", 0.6, 0.55)
c = replace_param(c, "min_history", 80, 50)
f.write_text(c)
changes["double_decay_reversal"] = "P90→P80, decay 0.50/0.25→0.70/0.50, no RSI gate, direction 0.60→0.55"

# ── 4. exhaustion_fade ──
# P95→P80, decay_bars 3→1, decay_ratio 0.3→0.5, disable BB confirmation
f = BASE / "strategies/reversal/exhaustion_fade.py"
c = f.read_text()
c = replace_param(c, "cascade_percentile", 95, 80)
c = replace_param(c, "decay_bars", 3, 1)
c = replace_param(c, "decay_ratio", 0.3, 0.5)
c = replace_param(c, "use_bb_confirmation", "True", "False")
c = replace_param(c, "min_history", 100, 50)
f.write_text(c)
changes["exhaustion_fade"] = "P95→P80, decay_bars 3→1, ratio 0.30→0.50, no BB confirm"

# ── 5. hlp_zscore_reversal ──
# Lower min_liq_usd, shorter lookback, lower z-score thresholds
f = BASE / "strategies/generated/hlp_zscore_reversal.py"
c = f.read_text()
c = replace_param(c, "min_liq_usd", 100, 1)
c = replace_param(c, "zscore_lookback", 30, 15)
c = replace_param(c, "zscore_long_threshold", 1.2, 0.8)
c = replace_param(c, "zscore_short_threshold", -1.2, -0.8)
c = replace_param(c, "min_history", 40, 20)
c = replace_param(c, "ratio_smoothing", 5, 3)
f.write_text(c)
changes["hlp_zscore_reversal"] = "min_liq $100→$1, z-score ±1.2→±0.8, lookback 30→15, smooth 5→3"

# ── 6. hyperliquid_liq_grid ──
# P90→P80, disable RSI confirmation (too restrictive), lower min_liq
f = BASE / "strategies/generated/hyperliquid_liq_grid.py"
c = f.read_text()
c = replace_param(c, "liq_percentile", 90, 80)
c = replace_param(c, "min_liq_usd", 1000, 100)
c = replace_param(c, "use_rsi_confirm", "True", "False")
c = replace_param(c, "max_wick_atr", 2.0, 3.0)
f.write_text(c)
changes["hyperliquid_liq_grid"] = "P90→P80, min_liq $1K→$100, no RSI confirm, wick ATR 2→3"

# ── 7. liquidation_sniping ──
# P95→P85, widen RSI reversal protection (allow more entries), lower confirm_body_atr
f = BASE / "strategies/generated/liquidation_sniping.py"
c = f.read_text()
c = replace_param(c, "liq_percentile", 95, 85)
c = replace_param(c, "rsi_reversal_long", 65, 80)
c = replace_param(c, "rsi_reversal_short", 35, 20)
c = replace_param(c, "confirm_body_atr", 0.2, 0.1)
c = replace_param(c, "min_liq_usd", 500, 100)
f.write_text(c)
changes["liquidation_sniping"] = "P95→P85, RSI protect 65/35→80/20, body ATR 0.2→0.1, min_liq $500→$100"

# ── 8. weekly_low_accumulation ──
# RSI 30/70 → 35/65 (hardcoded in on_candle), lower min_history, add stop_loss
f = BASE / "strategies/generated/weekly_low_accumulation.py"
c = f.read_text()
# Fix the hardcoded RSI thresholds
c = c.replace("current_rsi > 70 or current_rsi < 30", "current_rsi > 65 or current_rsi < 35")
c = c.replace('direction = -1 if current_rsi > 70 else 1 if current_rsi < 30 else None',
              'direction = -1 if current_rsi > 65 else 1 if current_rsi < 35 else None')
# Lower min_history: change max_history // 2 to 50
c = c.replace('self.get_param("max_history") // 2', '50')
f.write_text(c)
changes["weekly_low_accumulation"] = "RSI 30/70→35/65, min_history 150→50"

# Print summary
print("=" * 70)
print("  STRATEGY THRESHOLD MODIFICATIONS")
print("=" * 70)
for name, desc in changes.items():
    print(f"  {name:30s} → {desc}")
print("=" * 70)
print(f"\n  {len(changes)} strategies modified.")
