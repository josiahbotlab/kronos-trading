"""
Augxmented Strategy Configuration
===================================
Constants, weights, session rules, and detector parameters.
"""

# Signal scoring weights — each confluence contributes to total score
WEIGHTS = {
    'fvg_present': 2,
    'inverse_fvg': 2,
    'order_block': 2,
    'breaker_block': 2,
    'bos_trigger': 3,
    'smt_divergence': 2,
    'htf_structure_1h': 1,
    'htf_structure_4h': 2,
    'premium_discount': 1,
    'volume_spike': 1,
    'rsi_divergence': 1,
    'session_quality': 1,
}
MINIMUM_SCORE = 13
BOS_REQUIRED = True

# Session rules (Eastern Time)
FORBIDDEN_TIMES_ET = [('00:00', '01:00'), ('12:00', '14:00'), ('18:00', '20:00')]
BEST_SESSIONS = [('09:30', '11:30'), ('02:00', '05:00')]
NO_ENTRY_BEFORE_ET = '09:30'
NO_ENTRY_AFTER_ET = '15:30'

# Detector parameters
FVG_MIN_GAP_ATR_MULT = 0.3       # FVG gap must be >= 30% of ATR
OB_MOVE_ATR_MULT = 1.5           # OB requires 1.5x ATR move after
BOS_SWING_LOOKBACK = 20          # Bars to find swing H/L for BOS
STRUCTURE_SWING_LOOKBACK = 10    # Bars for HH/HL/LH/LL detection
VOL_SPIKE_MULT = 1.5             # Volume > 1.5x avg = spike
SMT_LOOKBACK = 20                # Bars to compare QQQ vs SPY swings
