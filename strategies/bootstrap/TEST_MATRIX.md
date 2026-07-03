# Strategy Test Matrix — standing checklist

**Canonical baseline:** `baseline_800_v4.json` · sha256 `615e9414ce0db99d3864f7f4a443a61488c6dc0391fd7150c5e72537db098b12`
**Pool:** `pools/fleet_trades_v4.json` (2341 trades) · **Costs everywhere:** $1.24/RT + 1.0pt slip · **Method:** one axis at a time, others at baseline.

This is a PERSISTENT worklist, not a one-shot. Each cell: **STATUS** (untested / running / pass / fail / partial / deployed / n-a), best value, PF, net$, Stage-2.

### GATE (a result only "counts" if it clears this)
- **Stage-1:** PF > 1.1 **AND** net$ holds (no gutting trade count for fake PF) **AND** IS/OOS signs agree.
- **Stage-2:** walk-forward + bootstrap **drop-top-3** + worst-regime + fleet-add lift.
- **Auto-reject:** collapses when top-3 wins dropped, or IS/OOS disagree, or dies at 1.0pt slip.

---

## ORB  (⭐ Stage-2 VALIDATED: **15m + trail-after-3R** 2026-07-02 · realistic PF 6.04 / net$ 11892 / n=360 · vs 15m-4R PF 3.61/$8653 · vs 1m PF 1.32/$2459.  NOTE: other axis rows were tested at the 1m/4R baseline — re-sweep at 15m+trail pending.)
| # | Axis | Options | STATUS | Best | PF | net$ | S2 | Notes |
|---|------|---------|--------|------|----|----|----|-------|
|1|Entry side|long/short/both|**deployed**|both|1.32|2459|n-a|first-break either dir + clean-bias|
|2|Instrument|NQ/ES/YM/RTY(+µ)|**partial**|NQ|1.32|2459|—|ES=partial (0.92@1pt slip-fragile, corr 0.12); **RTY=FAIL** (ORB-RTY PF 0.99 / net −$116, IS/OOS disagree; corr 0.05 real but neg-exp); YM untested (no data)|
|3|Timeframe|1/3/5/15/30m|**pass**|**15m**|3.61|8653|✓|**Stage-2 PASS all 5 gates** (WF 13/13, drop-top-5 holds 3.52, IS/OOS 3.66/3.58 agree, 1.5pt slip 3.19, fleet-add +16.95pp). Realistic 1m-resolved fills (pessimistic floor 2.44). Monotonic 1m→3→5→15: PF 1.32/1.49/1.73/3.61|
|4|Session|Lon/NYopen/lunch/aft/ON|**deployed**|NY-open|1.32|2459|n-a|other windows untested for ORB|
|5|Trigger|breakout/retest/pullback/mom|**partial**|breakout|1.32|2459|—|breakout=deployed; retest/pullback/momentum untested|
|6|OR length|5/15/30/60m|**partial**|15m(08:45-09:00)|1.32|2459|—|08:00-08:15 historically OOS 0.97; 5/30/60 not swept at 1pt|
|7|Stop|fixed/ATR/structure/BE-trail/step-trail|**deployed**|structure(range)|1.32|2459|n-a|trailing variants untested|
|8|Take-profit|fixedR/ATR/tiered/runner/**trail**|**pass**|**trail-after-3R**|6.04|11892|✓|**Stage-2 PASS all gates**: drop-top-5 holds $10666 (still > 4R-full $8653), bootstrap 100%>$8653, WF 12/13, worst-regime PF 2.78, 1.5pt slip 5.33. Realistic 1m-walk trail. +37% net vs 4R-fixed. Also swept: TP 2/3/5/6R (4-5R best fixed), ATR stops = risk-inflation (PF~1.6, maxDD 10-17× — reject), tiered = less net|
|9|Max trades/day|1/2/unlimited|**deployed**|1|1.32|2459|n-a|2 & unlimited untested|
|10|Filters|vol/vol-regime/DoW/HTF/compression/SMT|**fail**|none|—|—|✗|**NR7 FAIL** (PF 1.08); **NR4 FAIL** (flat 1.30, dollars gutted 5×); **200SMA-regime FAIL**; **SMT FAIL** (no help); volume/vol-regime/DoW/HTF untested|

## DONCHIAN  (Stage-2 VALIDATED · PF 1.18 / net$ 7190 @3 MNQ · thin: drop-5 negative)
| # | Axis | Options | STATUS | Best | PF | net$ | S2 | Notes |
|---|------|---------|--------|------|----|----|----|-------|
|1|Entry side|long/short/both|**pass**|long-only|1.18|7190|✓|**short/both = FAIL** (2026-07-02): short-only PF 0.78/net −$1916, combined breaks IS/OOS (1.04/0.91) & net −$1343, fleet-add −6.10pp (58.58→52.48%). NQ down-moves choppy/squeeze — Don STAYS long-only|
|2|Instrument|NQ/ES/YM/RTY(+µ)|**partial**|NQ|1.18|7190|✓|ES=partial (PF 1.14, corr 0.54); **RTY=FAIL** (Don-RTY PF 0.40 / net −$4034; corr 0.12 real but strong loser); YM untested (no data)|
|3|Timeframe|1/3/5/15/30m|**partial**|5m|1.18|7190|✓|5m validated; 1/3/15/30 untested|
|4|Session|Lon/NYopen/lunch/aft/ON|**partial**|Lon+NYopen|1.18|7190|✓|KZ windows validated; lunch/afternoon/overnight untested|
|5|Trigger|breakout/retest/pullback/mom|**partial**|breakout|1.18|7190|✓|channel-breakout validated; retest/pullback/momentum untested|
|6|OR length|—|**n-a**|—|—|—|—|not an opening-range strategy|
|7|Stop|fixed/ATR/structure/BE-trail/step-trail|**pass**|1.5×ATR|1.18|7190|✓|other stop types untested|
|8|Take-profit|fixedR/ATR/tiered/runner|**partial**|2R fixed|1.18|7190|✓|**runner tested elsewhere = WORSE**; tiered untested|
|9|Max trades/day|1/2/unlimited|**pass**|1/day|1.18|7190|✓|**max-1 dominates raw**(unlimited=clusters losses); 2/day untested|
|10|Filters|vol/vol-regime/DoW/HTF/compression/SMT|**partial**|200SMA(with-trend)|1.18|7190|✓|200SMA is part of spec; volume/vol-regime/DoW/compression/SMT untested|

## KZ  (LOSER · PF 0.71 @3 MNQ / 0.88 @1.5× · negative-edge, being dropped)
| # | Axis | Options | STATUS | Best | PF | net$ | S2 | Notes |
|---|------|---------|--------|------|----|----|----|-------|
|1|Entry side|long/short/both|**fail**|both|0.71|-8585|✗|negative in every cut|
|2|Instrument|NQ/…|**fail**|NQ|0.71|-8585|✗|not tested elsewhere (base fails)|
|3|Timeframe|1/5m|**fail**|1m|0.71|-8585|✗|(5m "PF 1.31" was fantasy, never real)|
|4|Session|Lon/NYopen|**fail**|—|—|-8585|✗|**loses in BOTH London AND NY** (diagnostic) — no sub-session to keep|
|10|Filters|SMT|**fail**|—|0.88|—|✗|**SMT does NOT rescue** (0.88 on / still loser off); regime: loses above AND below 200SMA|

## TEMPLATE — NEW strategy `<name>`
| # | Axis | Options | STATUS | Best | PF | net$ | S2 |
|---|------|---------|--------|------|----|----|----|
|1|Entry side|long/short/both|untested|—|—|—|—|
|2|Instrument|NQ/ES/YM/RTY(+µ)|untested|—|—|—|—|
|3|Timeframe|1/3/5/15/30m|untested|—|—|—|—|
|4|Session|Lon/NYopen/lunch/aft/ON|untested|—|—|—|—|
|5|Trigger|breakout/retest/pullback/mom|untested|—|—|—|—|
|6|OR length|5/15/30/60m|untested|—|—|—|—|
|7|Stop|fixed/ATR/structure/BE-trail/step-trail|untested|—|—|—|—|
|8|Take-profit|fixedR/ATR/tiered/runner|untested|—|—|—|—|
|9|Max trades/day|1/2/unlimited|untested|—|—|—|—|
|10|Filters|vol/vol-regime/DoW/HTF/compression/SMT|untested|—|—|—|—|

---

## GLOBAL FINDINGS (apply across strategies — do not re-test)
- **Mean-reversion / reversal / pullback-to-mean = DEAD on NQ.** Failed: dip-buy, RSI-fade, VWAP-reversion, PDL break-retest, JJ-Simon reversion phase, parabolic-fade, "V-shape" reversals. Any *reversion* trigger → auto-reject.
- **Sizing-up = blows up.** KZ at 4/5 MNQ → MLL blowout 35–43%. Variance scaling is a trap above ~3 MNQ.
- **Cross-instrument reality:** ES = marginal (ORB-ES slip-fragile at 1pt; Don-ES half-redundant corr 0.54). **RTY = TESTED 2026-07-02, FAIL** — ORB-RTY PF 0.99 / Don-RTY PF 0.40, decorrelated (corr 0.05 / 0.12) but negative-expectancy; a decorrelated *loser* is worthless (the "37% fleet-add" was a KZ-trap variance mirage). **GC / CL / YM = no data, untested.**
- **ORB filters that FAIL:** NR7, NR4, 200SMA-regime, SMT. Cutting trade count has not once raised ORB PF.
- **ORB = 15m + trail-after-3R (VALIDATED 2026-07-02).** 1m→15m tripled the edge (PF 1.32→3.61); trail-after-3R lifted it further to realistic PF 6.04 / net $11892 (drop-top-5 holds — not tail-driven). **KZ-free ORB-15m-trail2 + Don3 = 58.58% any-of-5** — best lineup found (vs 47.70% with 15m-4R, 30.75% with ORB-1m). Correct $12 Don slip.
- **ORB-15m-trail OOS ROBUSTNESS (2026-07-03):** holds ALL 5 years **2022-2026** — PF **6.18 / 4.81 / 4.78 / 6.62 / 7.79**, positive net every year, WR 67-71%, maxDD ≤$195. **2022-2023 = genuine OOS** (built only on 2024-2026); **2022 bear = 2nd-best year (PF 6.18, $10,155)**. **Paper's 2024-only-regime warning REFUTED** for the 15m-trail variant. OOS data `data/nq_1m_2022_2023_front.parquet` (707,510 bars, continuous front-month, saved uncommitted).
- **REGIME CLASSIFIER (Volatility-Volume-Gap, 3-state GMM) — built & CLEAN, but NO EDGE (2026-07-03).** Stage 1: lookahead-free (100% truncation-invariant; expanding-window GMM refit daily, F3 rolling-20 ending T-1, label available ~10:00 ET; all 3 regimes present every year 2022-2026). Stage 2: **NO independent regime edge** — **zero (regime/transition × horizon) cells clear |t|>3** after 2.62pt cost; the paper's "transitions predict direction" finding does **NOT replicate** on NQ 2022-2026 (largest signals |t|<1.85 = noise). ORB-15m-trail marginally better on **calm/R0 days (PF 6.77 vs 5.62 volatile, maxDD $64 vs $106)** = **minor optional sizing lever only**. **Regime-timing strategy REJECTED — would fit noise; Stage 3 skipped.**
- **INFLUENCER STRATEGY BATCH — all REJECT (2026-07-03), full 2022-2026 stitched, realistic $1.24/RT+1pt:**
  - **JJ Simon Fair Value Theory = FAIL** — net **−$33,514**, every phase (continuation/reversion) × window (AM/PM), PF 0.69-0.77, IS/OOS both <1. (Re-confirmed the earlier 2024-26 reject on fuller data.)
  - **ALN overnight-range bias = FAIL** — NOISE: no (pattern/transition) cell clears |t|>3; the "leans" carry ~0 directional bias (bull-lean mean NY return −0.0pt); nothing tradeable after cost.
  - **Trader Kane Lab Model = FAIL (FAITHFUL build)** — proper ES-vs-NQ SMT divergence + proper 3-bar iFVG: **PF 0.68, net −$2,704, IS 0.58 / OOS 0.93 (both <1)**, loses every year except a marginal 2025 (n=24). **The earlier approximated PF 3.40 (n=65, 2024-26) was an APPROXIMATION ARTIFACT — REFUTED by faithful implementation + OOS.** Lesson: loose ICT approximations (window-max SMT, displacement-as-iFVG) manufacture false positives; faithful build + pre-2024 OOS killed it.
  - **Durable asset:** ES 2022-2023 continuous front-month now on box — `data/es_1m_2022_2023_front.parquet` (707,317 bars, 9 quarterly rolls, stitches clean to es_1m_db) — reusable for any future ES/SMT work.
- **NQ INTRADAY/WEEKDAY/OVERNIGHT SEASONALITY = NO EDGE (2026-07-03).** Structural drift test, full 2022-2026, causal, IS 2022-24 / OOS 2025-26. **NOTHING clears IS |t|>3 + OOS-sign-agree.** 30-min RTH buckets = **noise** (max IS |t|≈2.0; signs FLIP IS↔OOS — 10:00 −2.50→+2.60, 11:00 +2.71→−0.16, 14:30 +3.07→−3.67). **Monday-positive** drift (+25.8 IS/+51.6 OOS, 58-64% hit) and the **overnight premium** (drift > RTH, positive both periods) are REAL but **sub-threshold (~2σ, |t|<2.4)** — not tradeable vs 2.6pt RT cost. **Structural-seasonality angle = no deployable edge. DO NOT RE-TEST.**
- **OKALA 80/20 (:20/:80 round-number fade + break, VWAP-filtered) = FAIL (2026-07-03).** Full NQ 2022-2026, IS 2022-24 / OOS 2025-26, pre-committed mechanics LOCKED (levels @ price%100∈{20,80}; touch≤1pt; rejection wick≥5pt close-back fade toward VWAP, stop 2pt beyond wick, 2R; continuation close≥5pt beyond away from VWAP, stop 2pt origin side, 2R; max 1/level/session; RTH flat 15:55), realistic 1m SL-first fills + $1.24/RT + 1pt/side. **Rejection-only PF 0.75 (−$15,152) · Continuation-only PF 0.80 (−$19,547) · Combined PF 0.78 (−$34,699).** WR ~33% at 2R = breakeven-neutral; costs push it **net-negative EVERY year 2022-2026** (PF 0.65-0.98, none clears 1.0), avgR −0.18. Round-number effect is real (Part-A t~4.9) but the **mechanical edge does NOT beat cost.** **DO NOT RE-TEST.**
- **OKALA FORK (round-number rejection-wick + aggressive-move-into-level) = FAIL (2026-07-03).** Approximation from public method summaries (not the paid course). NQ 2022-2026, 5m signal / 1m SL-first fills, $1.24/RT + 1pt/side, RTH 09:30-11:30 flat; LOCKED mechanics (level :20/:80 tol 2pt; ≥1.5×ATR(14,5m) move into level within last 3 bars + rejection candle reaching level & closing back with ≥50% wick; entry rejection-close, stop 2pt beyond wick, 2R; max 1/level/session). **Long PF 0.96 (−$1,273) · Short PF 0.92 (−$2,162) · Combined PF 0.94 (−$3,435).** IS 0.89 / OOS 0.99 (both <1), WR 36% at 2R ≈ breakeven, 2022 bear PF 0.74. The wick + aggression filters tighten it to near-breakeven but it still does NOT beat cost. **DO NOT RE-TEST.** (Okala family now closed: 80/20 mechanical PF 0.78; Okala-as-filter on ORB/Don = no effect; Fork PF 0.94 — round-number geometry has no deployable edge on NQ.)

## RANKED HIGHEST-VALUE UNTESTED CELLS (real hypothesis, not grid-fill)
1. ~~RTY instrument~~ — **DONE 2026-07-02: FAIL** (both edges negative-expectancy on Russell; decorrelated but worthless). → **New #1 = ORB timeframe sweep (item 2).**
2. ~~ORB timeframe sweep~~ — **DONE 2026-07-02: 15m WINS, Stage-2 PASS** (realistic PF 3.61 vs 1m 1.32; fleet ORB-15m2+Don3 = 47.70% any-of-5). → **New #1 = Donchian short-side (item 3).**
3. ~~Donchian short-side~~ — **DONE 2026-07-02: FAIL** (short-only PF 0.78, combined breaks IS/OOS + fleet −6pp; NQ shorts choppy/squeeze). → **New #1 = Donchian timeframe sweep (item 4).**
4. **Donchian timeframe sweep (1/3/15/30m)** — cheap free-upside check.
5. **Breakout-RETEST trigger (ORB + Donchian)** — enter on pullback to the broken level instead of at break; better R:R hypothesis, may lift thin Donchian PF.
6. **ORB tiered-partials / runner TP** — capture trend-day extension beyond fixed 4R.
7. **Volume-confirmation filter (ORB + Donchian breakouts)** — filter false breakouts; the one filter family not yet tried on ORB.
8. **ORB max-2/day** — currently 1/day; a second qualified setup may add uncorrelated trades.

_Last updated: 2026-07-03 (NQ seasonality = NO edge, nothing clears |t|>3; influencer batch ALL FAIL JJ/ALN/Kane [Kane PF-3.40 = approximation artifact, faithful = 0.68]; regime classifier CLEAN but NO edge; ORB-15m-trail OOS-ROBUST 2022-2026). Deployable set unchanged: ORB-15m-trail + Don-long, KZ-free fleet 58.58%._
