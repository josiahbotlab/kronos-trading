# Strategy Registry

Single source of truth for every strategy that's been considered, coded, paper-traded, or deployed. Updated as state changes — promote on validation, demote on failure.

**Path:** `/home/agent/kronos-trading/strategies/STRATEGY_REGISTRY.md`

---

## Stages

| Stage | Meaning | Lives in |
|---|---|---|
| `research` | Idea/concept, no code | `research/` |
| `backtest` | Coded, historical evaluation in progress | `backtest/` |
| `paper` | Paper bot deployed, accumulating signals | `paper/` |
| `live` | Paper-validated, routed to TopStep | `live/` |
| `retired` | Removed after paper or live failure | `retired/` |

State transitions: `research` → `backtest` → `paper` → `live` → `retired`. Skipping stages is allowed if justified in the notes.

---

## Live

### AUGXMENTED_NQ_1M_KZ
- **Stage:** live (since 2026-06-26 — replaced AUGXMENTED_1M_KZ_PAPER which traded QQQ via Alpaca with a 17-min delay)
- **Edge Hypothesis:** ICT confluence (BOS, FVG, OTE) gated by kill zone + Variant C regime (NQ=F 200d SMA direction filter)
- **Timeframe:** 1m
- **Kill Zone / Session:** ET 03:00-05:00 (London), ET 09:30-11:30 (NY Open)
- **Data Needed:** MNQ 1m via TopStepX SignalR; NQ daily for 200d SMA regime gate (currently yfinance); MES 1m for SMT confluence — **deployed without SMT**, labeled clearly until MES tick history is wired into the backtest harness
- **Key Metrics (6mo backtest, 2 MNQ, $1.24/RT comm, without SMT):** 178 trades · WR 75.3% · PF 1.34 · Total +$2,730 · Avg winner $80 · Avg loser $183
- **Contract count:** 3 MNQ (raised from 2 MNQ on 2026-06-27 after bootstrap sim showed 5-acct pass rate 52% at 3 MNQ vs 7% at 2 MNQ; daily-loss-fail share 14% at 3 MNQ — acceptable)
- **Notes:** Original QQQ-Alpaca version retired due to 17-min IEX feed delay. NQ replacement deployed via SignalR with ~2s bar latency.

### ORB_8AM
- **Stage:** live (Beelink executor route activated 2026-06-27)
- **Edge Hypothesis:** Opening Range Breakout — first close past 08:45-09:00 ET zone is directional bias; pullback to zone mid is entry
- **Timeframe:** 1m
- **Kill Zone / Session:** Zone formation 08:45-09:00 ET · trade window 09:00-12:00 ET · EOD close 15:30 ET
- **Data Needed:** NQ 1m via TopStepX SignalR; Asia/London session H/L for stop hunt
- **Key Metrics (2.5-yr backtest, 1 MNQ):** 452 trades · WR 33.8% · PF 1.86 · Total +$4,423 · Avg winner $63 · Avg loser $17 (4R TP design — losers small, winners 3-4x bigger)
- **Contract count:** 1 MNQ
- **Notes:** No regime gate by design — relies on the 4R TP structure for positive expectancy. Cleanest standalone edge of the four live strategies; largest sample; longest history.

### LONDON_SWEEP_FVG
- **Stage:** live
- **Edge Hypothesis:** Sweep of London H/L → FVG forms in reversal direction → fade with stop at sweep candle, TPs at 1R/2R/opposing H/L
- **Timeframe:** 1m
- **Kill Zone / Session:** London H/L locked 03:00-08:00 ET · trade window 08:00-14:00 ET · EOD 16:00 ET
- **Data Needed:** NQ 1m via TopStepX SignalR; NQ daily for 200d SMA regime gate
- **Key Metrics (2.5-yr backtest, 1 MNQ):** 54 trades · WR 55.6% · PF 1.22 · Total +$113 · Avg winner $21 · Avg loser $22
- **Contract count:** 1 MNQ
- **Notes:** Low trade frequency (~1.8/mo). Edge is real but thin and sample-sensitive. Watch for sustained underperformance — if rolling 20-trade PF stays < 1.1 for 60 days, retire.

### GAP_FADE_QQQ
- **Stage:** live
- **Edge Hypothesis:** Overnight QQQ gap >0.15% fades to prior close (mean-reversion of opening overreaction)
- **Timeframe:** 1m
- **Kill Zone / Session:** Single signal at 09:30 ET market open
- **Data Needed:** QQQ 1m via Alpaca IEX (16-min clamp removed 2026-06-26 — measured delay ~2 min)
- **Key Metrics:** **No trades fired yet.** Threshold lowered from 0.3% → 0.15% on 2026-06-27 after `gap_fade_qqq_paper_trades` showed 0 rows over weeks at 0.3%.
- **Contract count:** 1 MNQ
- **Notes:** Dormant slot. If still 0 trades after 30 days at 0.15%, retire or lower further.

---

## Retired

### AUGXMENTED_NQ_5M
- **Stage:** retired (2026-06-27)
- **Edge Hypothesis (intended):** Same Augxmented confluence on NQ 5m with ES SMT and Variant C regime
- **Timeframe:** 5m
- **Kill Zone / Session:** UTC 07:00-11:00 (London), UTC 13:00-18:00 (NY)
- **Data Needed:** MNQ 5m + MES 5m via TopStepX SignalR; NQ daily for regime
- **Key Metrics (99-day backtest, 1 MNQ, $1.24/RT comm):** 43 trades · WR 62.8% · **PF 0.79 net (LOSING)** · Total **−$476** · Avg winner $65 · Avg loser $140
- **Contract count (when live):** 1 MNQ
- **Removed because:** Net negative after commission. PF < 1 confirms no edge at this size and timeframe. Removed from `MNQ_CONTRACTS_BY_STRATEGY` on all 5 Beelink confs; systemd unit stopped + disabled on VPS 2026-06-27 21:18 UTC.
- **Retire decision basis:** /tmp/bootstrap_sweep.py results — removing the 5m bot raised single-account pass rate by ~30% in the contract sweep at all KZ contract counts.

---

## Backtest

### ASIAN_SESSION_LOW_LONDON_OPEN
- **Stage:** backtest (advanced to paper deploy 2026-06-28 — see Notes)
- **Edge Hypothesis:** During London Open (02:00-05:00 ET), price often sweeps below the Asian session low (12:00-02:00 ET range) then reclaims it. With a confirmation bar (next 1m close above the sweep bar close), the reclaim marks a liquidity-grab reversal long.
- **Timeframe:** 1m
- **Kill Zone / Session:** Asian range setup 12:00-02:00 ET · London Open trade window 02:00-05:00 ET · no new entries after 05:00 ET · max hold 60 bars (1 hr)
- **Data Needed:** MNQ 1m via TopStepX SignalR; NQ daily for 200d SMA regime gate (yfinance), long-only
- **Variant deployed (confirm-only):**
  - Sweep range filter (25pt cap) tested and dropped — ablation showed PF within noise (1.62 vs 1.72)
  - Entry: 1m bar where low ≤ Asian low AND close > Asian low, THEN next bar close > entry-bar close
  - Stop: sweep bar low (no buffer)
  - TPs: 0.5 / 1.0 / 1.5 × ATR(14) tiered (1/3 each), BE after TP1, lock 0.5R after TP2
- **Key Metrics (full 2.5yr, 1 MNQ, $1.24/RT comm):** 118 trades · WR 78.0% · PF 1.62 · Total +$210.26 · Avg winner $6.00 · Avg loser $13.14
- **Walk-forward (2024 train / 2025-26 test):** OOS 82 trades · WR 79.3% · PF 1.59 — edge holds out of sample with mild decay (IS PF 2.37 was small-sample noise)
- **TopStep bootstrap (1 MNQ standalone, 10k sims):** Single 0.00% · Any-of-5 0.00% — avg +$0.45/day cannot reach $3K target in 30 days
- **Fleet-add (current 3-strat mix + Asian/LO):** at 1 MNQ Δ −1.38pp any-of-5; at 3 MNQ Δ +0.03pp any-of-5 (indistinguishable from baseline)
- **Decision:** Paper-only deploy at 1 MNQ. Monitor 30 days (review **2026-07-30**, joint review with FHB_RANGE225 sibling). If 78% WR holds live, revisit R-multiples (wider stops + further TPs) to scale per-trade dollar size. **Do not deploy to executor yet.**
- **Notes:** Source: tradethatswing.com RSS feed via the auto-scraper. Supersedes the prior `ASIAN_RANGE_SWEEP` research entry (which was the bidirectional concept — this is the implemented long-only LOW-sweep variant).

---


### FIRST_HR_BREAKOUT_SHORT
- **Stage:** backtest (advanced to paper deploy 2026-06-30 — see Notes)
- **Edge Hypothesis:** First-hour opening range (09:30-10:30 ET) breakout — when the FIRST break of the range is to the downside, the day's directional bias is short. Short side carried the full FHB strategy ($+6,379 vs −$5,928 longs in 2.5yr backtest); long-side breaks are skipped entirely.
- **Timeframe:** 1m
- **Kill Zone / Session:** Range formation 09:30-10:30 ET · trade window 10:30-15:55 ET · flat 15:55 ET · max 1 trade/day
- **Data Needed:** MNQ 1m via TopStepX SignalR; NQ daily for 200d SMA regime gate (yfinance), short-only (short_allowed = close < SMA)
- **Variant deployed (short-only):**
  - Skip day entirely if first break after 10:30 is to the UPSIDE
  - Skip day if first bar breaks both sides (ambiguous)
  - Entry: stop-order fill at fh_low on first downside break
  - Stop: fh_high (full FH range as risk)
  - TP: 2R (entry − 2×(stop − entry)) — fixed, no partials
  - 15:55 ET force-flat if neither stop nor TP hit
- **Key Metrics (full 2.5yr, 3 MNQ, $1.24/RT comm):** 273 trades · WR 53.1% · PF 1.19 · Total +$6,379 · Avg winner $280 · Avg loser $267 · 9.2 trades/mo · 2 cap-trip days (down from FHB-full's 6)
- **Slip stress (+1pt/fill):** PF 1.09 · Total +$3,103 (positive expectancy intact)
- **TopStep bootstrap (canonical 52.37% baseline):** Single 13.52% → 28.32% (Δ +14.80pp) · **Any-of-5 52.37% → 80.26% (Δ +27.89pp)** · +1pt slip 76.73% (Δ +24.36pp)
- **Fail-mode shift:** time-fail 52.8% → 35.9% (Δ −16.9pp, attacks the 30-day clock) · daily-cap 33.7% → 35.8% (Δ +2.1pp, much cleaner than FHB-full's +9.4pp)
- **Median days-to-$3K:** 24 → 20 single / 23 → 17 any-of-5
- **Decision:** Paper-only deploy at 1 MNQ. Monitor 30 days (review **2026-07-30**, joint review with FHB_RANGE225 sibling). Promotion to executor requires: (1) walk-forward 2024 IS / 2025-26 OOS confirms variance edge isn't regime-specific, (2) realistic slippage on stop-order short entries (FH breaks are momentum), (3) live cap-trip rate matches backtest's ~1/year per acct.
- **Notes:** Deployed 2026-06-30 as `fhb-short-paper-bot.service` (enabled+started on VPS, 1 MNQ paper sizing). Journal table `fhb_short_paper_trades` in trade_journal.db. TG messages use `📄 PAPER FHB_SHORT` prefix WITHOUT 🎯 — Beelink executor RE_ENTRY regex does NOT match these signals. Source variant of FIRST_HR_BREAKOUT in `BACKTEST_QUEUE.md` (Done caveat) — short-only is strictly better than full variant on cap-risk axis with comparable any-of-5 lift.

---


### DONCHIAN_BREAKOUT_MAX1
- **Stage:** ✅ VALIDATED — Stage-2 gauntlet passed 2026-07-02 (against HONEST SMT-on v3 baseline) · paper-deployed since 2026-07-01
- **Edge Hypothesis:** Classic Donchian channel breakout on NQ 5m — close above the N=12 upper channel (shifted 1 bar, so no look-ahead) signals a fresh directional move. Long-only, gated by daily 200d SMA regime. The **max-1-entry-per-day filter** removes cluster-day cap risk: on wide-ATR days the raw strategy fires 3-6 times in the same trend and clusters losses; capping at 1 chronological entry per day cuts single-day exposure without hurting the setup edge.
- **Timeframe:** 5m (native — MNQFeed tf_minutes=5)
- **Kill Zone / Session:** KZ London 03:00-05:00 ET · NY Open 09:30-11:30 ET · flat 16:00 ET · max hold 90 5m bars (~7.5hr) · max 1 entry/day
- **Data Needed:** MNQ 5m via TopStepX SignalR; NQ daily for 200d SMA regime gate (yfinance), long-only
- **Variant deployed:**
  - Donchian N=12 upper/lower from bars strictly BEFORE current (`rolling(12).max().shift(1)`)
  - Entry: close > shifted upper channel; only inside KZ London OR NY Open windows
  - Stop: entry − 1.5×ATR(14, 5m); TP: entry + 2R hard
  - Exit: stop / TP / close < shifted lower channel / 16:00 ET flat / 90-bar max-hold
  - Max 1 entry/day (the winning filter — strictly dominates raw + all other tested filters at real -$800 cap)
- **Key Metrics (2.5yr, 3 MNQ, max-1/day filter):** 381 trades · PF 1.13 · +$25.18pp slip lift (vs canonical -$800 baseline 50.87%) · daily-cap Δ **-1.84pp (IMPROVES cap-fail below baseline)** · time-fail Δ -11.24pp
- **Head-to-head at real -$800 cap (canonical fleet baseline 50.87%):** DONCHIAN + max 1/day +25.18pp lift / -1.84pp cap · RAW DONCHIAN +30.05pp / +14.75pp cap · FHB_SHORT +19.32pp / +11.30pp cap · FHB_RANGE225 not re-tested at -$800 (only -$1K numbers on record) · FHB_full +16.58pp / +17.64pp cap. **max-1/day strictly dominates FHB_SHORT on both lift AND cap-cleanness at real threshold.**
- **Contract count:** 1 MNQ paper (backtest numbers were 3 MNQ; paper uses 1 MNQ for canonical paper-first cadence)
- **✅ STAGE-2 GAUNTLET (2026-07-02 — vs HONEST SMT-on v3 baseline; supersedes the DEPRECATED 50.87%/52.37% fantasy-baseline metrics above):**
  - Frozen: N=12 · 5m · max-1/day · long-only · with-trend (Variant C 200d SMA) · stop 1.5×ATR(14) · TP 2R · KZ London 03:00-05:00 + NY-open 09:30-11:30 ET (a MORNING breakout, not afternoon). n=377 · WR 36% · **PF 1.13 @0.5pt** (1.18 @0-slip · +$7,190/2yr @3MNQ · +$5,321 @0.5pt).
  - **Walk-forward** (90d test / 60d step): **6/9 windows profitable · mean PF 1.21 · median 1.07** (all windows ≥8 trades, 41-60 mostly). Robust window-to-window.
  - **Bootstrap** (10k): PF median 1.12 [5th 0.91, 95th 1.39] · **81% profitable · 57% PF>1.1**. Drop-top: drop-1→1.09 · **drop-3→1.02 (+$657)** · **drop-5→0.96 (−$1,508)**. ⚠️ THIN EDGE — survives drop-3, but drop-5 goes NEGATIVE. Not bomb-proof.
  - **Slip stress:** holds PF>1.0 through **1.5pt** (1.18/1.13/1.08/1.03 at 0/0.5/1.0/1.5pt). 2024 IS PF 1.25. Worst 2024 90d window PF 0.85.
  - **ORB-independence:** daily-PnL correlation **−0.01** (same-day 82% but P&L uncorrelated; DON fires London+NY, ORB NY-only) → genuinely diversifying.
  - **FLEET-ADD (honest @1pt):** **EDGES-ONLY (ORB2+Don3+LSF1) = 33.38% any-of-5 · MLL blow-up 8.3%** vs current fleet (KZ3+ORB1+LSF1) = 0.25% / 21.9%. Donchian needs 3 MNQ (at 2 MNQ only ~7%). This is the validated 0.25%→33% path — the fleet's genuine 2nd edge.
  - **CAVEATS:** thin edge (PF 1.13; drop-5 negative) — works IN the fleet by adding positive variance ORB lacks, not as a standalone star. Only **1 live paper fill** so far (a clean −1R stop, consistent w/ backtest) — needs ≥20-30 live fills to confirm breakout slippage before real size.
  - **VERDICT: REAL, robust, ORB-independent edge. Confidence moderate-high. NOT a mirage** (passed WF + bootstrap-drop-3 + slip + independence + fleet-lift, unlike every other 2026-07-02 candidate).
- **Decision:** Paper-only deploy at 1 MNQ. Monitor 30 days (review **2026-07-31**). Promotion to executor requires: (1) live trade frequency matches backtest (~12/mo; 381 trades / 30.5 mo), (2) live cap-fail rate stays negative or ≤ +2pp Δ, (3) walk-forward 2024 IS / 2025-26 OOS confirms edge isn't regime-dependent, (4) realized slippage stays ≤ 1pt (backtest survives 1pt slip stress).
- **Notes:** Deployed 2026-07-01 as `donchian-paper-bot.service` (enabled+started on VPS, 1 MNQ paper, PID 754934 at deploy). Journal table `donchian_paper_trades` in trade_journal.db (18 columns incl. session, upper_channel, lower_channel, atr, realized_r). TG messages use `📄 PAPER DONCHIAN` prefix WITHOUT 🎯 — Beelink executor RE_ENTRY regex does NOT match. Wired into `feed_drift_watchdog.py` (FEED_BOTS + BOT_ACTIVE_WINDOWS `[(3,0,5,0), (9,30,11,30)]`), `daily-bot-cycle.service`, `cme-break-cycle.service`. Per-bar heartbeat log emitted inside KZ windows. Winning filter identified vs the canonical -$800 fleet baseline (`/home/agent/kronos-trading/strategies/bootstrap/baseline_800.json`, reproduces 50.87% any-of-5).

---


### FIRST_HR_BREAKOUT_RANGE225
- **Stage:** backtest (advanced to paper deploy 2026-06-30 — see Notes)
- **Edge Hypothesis:** Same first-hour breakout mechanic as FIRST_HR_BREAKOUT, BOTH directions (long upside / short downside), with a single executable filter: skip the day entirely if the opening-range width exceeds 225pt. Diagnostic of FHB-full's 6 cap-trip days showed every cap day had FH range ≥ 190pt (top 25% widest); the 225pt cap removes 4 of 6 while preserving full FHB's any-of-5 lift.
- **Timeframe:** 1m
- **Kill Zone / Session:** Range formation 09:30-10:30 ET · trade window 10:30-15:55 ET · flat 15:55 ET · max 1 trade/day
- **Data Needed:** MNQ 1m via TopStepX SignalR; NQ daily for 200d SMA regime gate (yfinance), directional (long_allowed=close>SMA, short_allowed=close<SMA)
- **Variant deployed:**
  - Build FH range 09:30-10:30 ET; lock at 10:30
  - At 10:30: if (fh_high − fh_low) > 225pt → skip day entirely
  - Otherwise, on FIRST break after 10:30: LONG @ fh_high on upside, SHORT @ fh_low on downside
  - Skip day if both sides break in one bar (ambiguous)
  - Skip day if break direction is blocked by regime gate
  - Stop: opposite side of FH range; TP: 2R hard; 15:55 ET force-flat
- **Key Metrics (full 2.5yr, 3 MNQ, $1.24/RT, no SMT, range ≤ 225 filter applied):** 476 trades · 2 cap-trip days · total +$5,995 (vs FHB-full $451 / FHB-short $6,379)
- **TopStep bootstrap (canonical 52.37% baseline):** Single → 28.32%-ish (similar to short-only) · **Any-of-5 52.37% → 80.19% (Δ +27.82pp)** · +1pt slip 74.54% (Δ +22.17pp)
- **Fail-mode shift:** time-fail 52.8% → 37.0% (Δ −15.8pp) · daily-cap 33.7% → 34.6% (Δ +0.9pp — almost no degradation, matches short-only's +2.1pp)
- **Median days-to-$3K:** 24 → 21 single / 23 → 18 any-of-5
- **vs sibling FHB_SHORT:** matches on cap-days (2 vs 2), gives up ~2pp slip-resilience for ability to fire in any regime (longs available when NQ>SMA, shorts when NQ<SMA — no waiting for bear regime); +203 more trade samples (476 vs 273) means faster live-validation
- **Decision:** Paper-only deploy at 1 MNQ alongside FHB_SHORT (not as replacement). Two-bot parallel paper test. Monitor 30 days each (review **2026-07-30**) to compare: (a) live trade frequency vs backtest, (b) realized slippage on stop-order fills, (c) whether the range filter holds up live (no cap-trip days in paper window). If both bots clear paper, promote the better-performing one to executor.
- **Notes:** Deployed 2026-06-30 as `fhb-range225-paper-bot.service` (enabled+started on VPS, 1 MNQ paper sizing, PID 312334 at deploy). Journal table `fhb_range225_paper_trades` in trade_journal.db. TG messages use `📄 PAPER FHB_R225` prefix WITHOUT 🎯 — Beelink executor RE_ENTRY regex does NOT match. Runs alongside `fhb-short-paper-bot.service` with independent state and independent journal table.

---

## Research

### ZEN_MODEL
- **Stage:** research
- **Source:** Zen Trades Whop free course
- **Edge Hypothesis:** Liquidity sweep + HTF FVG delivery + IFVG entry + internal targets. V-shape close and SMT as bonus confluences.
- **Timeframe:** NQ 1m (mirrors current AUGXMENTED_NQ_1M_KZ)
- **Kill Zone / Session:** same as AUGXMENTED_NQ_1M_KZ (London 03:00-05:00 ET, NY Open 09:30-11:30 ET)
- **Data Needed:** MNQ 1m via TopStepX SignalR (already in place); HTF FVG/IFVG identification + premium/discount range tracker
- **Key Metrics:** none yet — core logic already implemented in AUGXMENTED_NQ_1M_KZ
- **Notes:** Most of the ZEN_MODEL ruleset is already in AUGXMENTED_NQ_1M_KZ. The two distinguishing filters (V-shape IFVG close, premium/discount entry gate) are queued as separate backtest items in `BACKTEST_QUEUE.md`: ZEN_MODEL_VSHAPE_FILTER (High) and ZEN_MODEL_PREMIUM_DISCOUNT_FILTER (Medium). Treat ZEN_MODEL itself as an umbrella concept; the queue items are the actionable evaluations.

### NY_LUNCH_REVERSAL
- **Stage:** research
- **Edge Hypothesis:** After NY lunch consolidation (12:00-14:00 ET), the first FVG fill in either direction marks a session-reversal entry. Lunch range provides clean SL.
- **Timeframe:** NQ 1m
- **Kill Zone / Session:** Setup window 12:00-14:00 ET · trade window 14:00-15:00 ET
- **Data Needed:** NQ 1m bars (already in `nq_1m_db`)
- **Key Metrics:** none yet
- **Notes:** Backtest priority is HIGH — full NQ 1m history available, low time-cost to evaluate. Define "lunch consolidation" precisely before coding (range threshold % of ATR, min N bars).

### ORB_REGIME_FILTER
- **Stage:** research
- **Edge Hypothesis:** ORB_8AM's 33.8% WR is dragged down by counter-trend signals. Adding (a) long-only filter when NQ above 200d SMA, (b) day-of-week filter dropping the worst day, may raise PF without halving trade count.
- **Timeframe:** NQ 1m
- **Kill Zone / Session:** same as ORB_8AM (08:45-09:00 zone, 09:00-12:00 trade)
- **Data Needed:** NQ 1m, NQ daily for regime; existing ORB_8AM trade pool for day-of-week stratification
- **Key Metrics:** none yet — but the 452-trade ORB pool already exists for direct analysis. Pre-backtest: stratify the 452 trades by weekday and by daily-SMA-regime, look at WR/PF per cell.
- **Notes:** Fastest research path — analyze existing pool first. Only build a new bot if stratification shows a removable subset of losers.

### NY_OPEN_IFVG
- **Stage:** research
- **Edge Hypothesis:** NY open (09:30 ET) liquidity grab → inverse FVG (iFVG = a fair-value gap that's been reversed) is a higher-confluence entry than Augxmented's wide-KZ pattern. Trades only the cleanest liquidity-sweep setups.
- **Timeframe:** NQ 1m
- **Kill Zone / Session:** 09:30-10:30 ET
- **Data Needed:** NQ 1m; pre-09:30 session high/low for "liquidity"
- **Key Metrics:** none yet
- **Notes:** Tighter sibling to AUGXMENTED_NQ_1M_KZ. Aim: fewer trades, higher PF. Risk: too tight → no trades (see GAP_FADE_QQQ). Define "iFVG" precisely before coding.

### VWAP_MEAN_REVERSION
- **Stage:** research (was archived 2026-06-02 at `strategies/archived/vwap_mean_reversion.py.archived` — failed 30-trade gate, WR 25%, PF 0.65, P&L −$41). Reviving as concept only.
- **Edge Hypothesis:** Use session VWAP as bias filter (above VWAP → only long, below → only short) layered onto ICT kill zone entries. Hypothesis: combining ICT confluence with institutional flow bias raises WR.
- **Timeframe:** NQ 5m
- **Kill Zone / Session:** London + NY KZ
- **Data Needed:** NQ 5m + session VWAP (computable from existing nq_5m + volume)
- **Key Metrics (archived prior version):** 280 historical rows in `data/execution.db`; WR 25% / PF 0.65 / −$41 — failed gate
- **Notes:** Prior failure was the VWAP-only standalone, not a VWAP-as-filter overlay on KZ entries. New version is a different design. Define entry strictly: KZ + ICT trigger + VWAP-bias-aligned only.

---

## Indexes (auto-pointers — keep in sync)

- Research-stage briefs: `research/`
- In-progress backtest harnesses: `backtest/`
- Paper bots deployed: `paper/`
- Live bot files (production): `live/`
- Retired strategies (with post-mortem): `retired/`
- Moon Dev concept candidates: `research/MOON_DEV_CANDIDATES.md`
- LLM-generated strategy stubs (361 files, mostly crypto, mostly untested): `generated/`

---

## Change log

- **2026-06-27** Registry created. Live: NQ_1M_KZ, ORB_8AM, LONDON_SWEEP_FVG, GAP_FADE_QQQ. Retired: NQ_5M. Research: 5 candidates seeded.

### Auto-scraped batch 2026-06-28
- **How to Trade the Asian Session Low Into London Open: A Step-by-Step Strategy** (score 6/10) — `2026-06-28_how_to_trade_the_asian_session_low_into_london_open_a_step-b.md` · [source](https://blog.trinitytrading.io/asian-session-low-london-open-strategy/)
- **2026-06-28** ASIAN_SESSION_LOW_LONDON_OPEN moved research → backtest (supersedes ASIAN_RANGE_SWEEP). Confirm-only variant: PF 1.62 (full), 1.59 (OOS). Paper-deploy at 1 MNQ. No executor routing.
- **2026-06-28** Created BACKTEST_QUEUE.md (one-backtest-per-day cadence, 7 seeded items in priority order). strategy_scraper.timer switched from weekly Sunday → daily 06:00 PT. asian-lo-paper-bot.service deployed on VPS (1 MNQ paper, no executor routing).
- **2026-06-28** Added ZEN_MODEL research entry (umbrella concept; Zen Trades Whop course). Distinguishing filters queued separately in BACKTEST_QUEUE.md: ZEN_MODEL_VSHAPE_FILTER (High) and ZEN_MODEL_PREMIUM_DISCOUNT_FILTER (Medium).
- **2026-07-01** Canonical bootstrap baseline re-frozen at real -$800 executor cap (was -$1K). Files moved to durable `strategies/bootstrap/`: `topstep_bootstrap.py`, `baseline_800.json` (any-of-5 50.87%, single 13.09%, fail_daily 47.80%, fail_time 39.11%), `fleet_baseline_helper.py` (overrides cap→$800 on import, reads baseline_800.json). Legacy `-$1K` retained as `baseline_1000_deprecated.json` for historical reference. Validation gate: helper reproduces 50.87% exactly. All future fleet-add candidates measured at -$800.
- **2026-07-01** DONCHIAN_BREAKOUT_MAX1 promoted backtest → paper deploy. New VPS service `donchian-paper-bot.service` (enabled+started, 1 MNQ paper, journal `donchian_paper_trades`). TG prefix `📄 PAPER DONCHIAN` — no 🎯 → no executor routing. Wired into `feed_drift_watchdog.py` (FEED_BOTS + BOT_ACTIVE_WINDOWS KZ hours), `daily-bot-cycle.service`, `cme-break-cycle.service`. Winning filter (max 1/day) strictly dominates FHB_SHORT at real -$800 cap on both lift (+5.86pp better) and cap-cleanness (+13.14pp better). Review 2026-07-31.
