#!/usr/bin/env bash
# rebuild_baseline.sh — DOCUMENTED PLACEHOLDER recording the exact source pools
# and commands used to build baseline_800_v4.json, so it can be regenerated.
# It does NOT auto-run: some intermediate artifacts (the KZ 1m SMT-on trade
# dump) were produced in /tmp and are not persisted.

# ============================================================================
# HARD GUARD — first executable code, runs before anything else.
# A rebuild may proceed ONLY when the canonical v4 baseline is already present
# and verified (sha 615e9414...098b12). This makes it impossible to rebuild on
# a blind/wiped session and silently overwrite the real baseline.
# ============================================================================
set -uo pipefail
GUARD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXPECTED_SHA="615e9414ce0db99d3864f7f4a443a61488c6dc0391fd7150c5e72537db098b12"
GATE_OUTPUT="$("$GUARD_DIR/check_baseline.sh" 2>&1)"; GATE_RC=$?
GATE_SHA="$(printf '%s\n' "$GATE_OUTPUT" | sed -n 's/^baseline sha256: //p' | head -n1)"
if [ "$GATE_RC" -ne 0 ] || [ "$GATE_SHA" != "$EXPECTED_SHA" ]; then
  echo "REFUSING: baseline gate failed, will not rebuild" >&2
  echo "  expected baseline sha256: $EXPECTED_SHA" >&2
  echo "  gate exit=$GATE_RC  observed sha256=${GATE_SHA:-<none>}" >&2
  exit 1
fi
# Gate passed — canonical v4 baseline present and verified. Safe to continue.

# ============================================================================
# CANONICAL POOL: strategies/bootstrap/pools/fleet_trades_v4.json
#   sha256 3d6036cc456f80c5f42c483fcf282e3866fb97b001964c73f62e912105a4fdf4
#   2341 trades total across 4 strategies.
#   net formula (all strategies): net = pts x $2/pt x baked_MNQ - baked_MNQ x $1.24
#
#   KZ  key AUGXMENTED_NQ_1M_KZ_WITHOUT_SMT (name legacy; DATA IS SMT-ON), 1073 trades
#       1-minute faithful backtest of the live AUGXMENTED_NQ_1M_KZ engine,
#       SMT-ON via Databento MES front-month proxy:
#         data/mes_1m_front.parquet  (continuous front-month, volume-roll,
#         built from data/GLBX-20260702-3JDCUHQFE6.zip via the MES front-month builder)
#       engine: strategies.augxmented RegimeStrategy at 1m, min_score 13,
#         TP 1.0/1.8/2.8, max_hold 120, hard_stop 2.5xATR(14),
#         KZ London 03:00-05:00 + NY-open 09:30-11:30 ET,
#         Variant-C regime = yfinance NQ=F daily 200SMA shifted 1 day (no lookahead).
#       baked 2 MNQ x sizing_mult 1.5 = 3 MNQ live. (PF 0.88, OOS 0.84 — KZ is a loser.)
#
#   ORB key ORB_8AM, 533 trades
#       backtest_orb_8am.run_variant(nq_1m_db, mode='A', clean_bias=True,
#         range_invalidation=False, zone_shift_min=45, tp_r_mult=4.0)
#       (Mode A / clean-bias ON / range OFF / zone 08:45-09:00 ET / TP 4R). baked 1 MNQ. PF 1.90.
#
#   LSF key LONDON_SWEEP_FVG, 356 trades
#       rebuilt from stock-trading/bots/london_sweep_fvg_paper_bot.py logic
#       (London H/L lock 03-08 ET, sweep >=2pt + close-back, skip range>20pt,
#        FVG entry, TP1 1R/TP2 2R/TP3 opposing H/L, Variant-C regime),
#       UNCAPPED-dedup variant (approximate: ~356 vs live ~287). baked 1 MNQ. PF 1.12.
#
#   DON key DONCHIAN_BREAKOUT_MAX1, 379 trades   (NEW in v4, added 2026-07-02)
#       N=12 / 5m / max-1-day / long-only / Variant-C 200SMA / stop 1.5xATR / TP 2R.
#       baked 1 MNQ. Present in the pool for future lineup sims but NOT yet in the
#       baseline sim composition (canonical_results are INHERITED from v3 = KZ/ORB/LSF).
#       TODO: exact build command / source module for Donchian is NOT recorded in
#       the pool or baseline; fill in from the Donchian backtester before any real
#       regeneration. Do not invent it.
#
# BASELINE SIM: strategies/bootstrap/topstep_bootstrap_v2.py  (any_of_5)
#   10,000 sims, 5 accounts, seeds ensemble=43 / single=42,
#   $50,000 -> $53,000 target, static $48,000 MLL floor, -$800 daily halt,
#   30-day window. Slip applied per strategy at live contract counts.
#   Sim composition = KZ/ORB/LSF only (Donchian is in the pool, NOT in the sim yet).
#   NOTE: static floor only — trailing DD and the 50% consistency rule are NOT modeled.
#
# TO REGENERATE (manual, in order):
#   1. Ensure data/mes_1m_front.parquet exists (rebuild from Databento MES zip if missing).
#   2. Re-run the KZ 1m SMT-on backtest -> KZ trades JSON.
#   3. Re-run ORB run_variant (above) and the LSF backtester.
#   4. Re-run the Donchian backtester (DONCHIAN_BREAKOUT_MAX1 params above). TODO: exact command.
#   5. Assemble pools/fleet_trades_v4.json using the net formula above
#      (KZ baked 2, ORB/LSF/DON baked 1); expect 2341 trades, sha 3d6036cc....
#   6. Run topstep_bootstrap_v2.any_of_5 at slip 0.0 and 1.0 -> canonical_results.
#   7. Write baseline_800_v4.json with source hashes + provenance + canonical=true.
# ============================================================================
echo "rebuild_baseline.sh: documented placeholder — see comments for the exact"
echo "source pools and commands used to build baseline_800_v4.json."
echo "Does not auto-run (KZ 1m SMT-on intermediate dump was in /tmp)."
exit 0
