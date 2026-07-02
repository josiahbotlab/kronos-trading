# Strategy Test Matrix — standing checklist

**Canonical baseline:** `baseline_800_v4.json` · sha256 `615e9414ce0db99d3864f7f4a443a61488c6dc0391fd7150c5e72537db098b12`
**Pool:** `pools/fleet_trades_v4.json` (2341 trades) · **Costs everywhere:** $1.24/RT + 1.0pt slip · **Method:** one axis at a time, others at baseline.

This is a PERSISTENT worklist, not a one-shot. Each cell: **STATUS** (untested / running / pass / fail / partial / deployed / n-a), best value, PF, net$, Stage-2.

### GATE (a result only "counts" if it clears this)
- **Stage-1:** PF > 1.1 **AND** net$ holds (no gutting trade count for fake PF) **AND** IS/OOS signs agree.
- **Stage-2:** walk-forward + bootstrap **drop-top-3** + worst-regime + fleet-add lift.
- **Auto-reject:** collapses when top-3 wins dropped, or IS/OOS disagree, or dies at 1.0pt slip.

---

## ORB  (deployed · baseline PF 1.32 / net$ 2459 / n=534 @1 MNQ)
| # | Axis | Options | STATUS | Best | PF | net$ | S2 | Notes |
|---|------|---------|--------|------|----|----|----|-------|
|1|Entry side|long/short/both|**deployed**|both|1.32|2459|n-a|first-break either dir + clean-bias|
|2|Instrument|NQ/ES/YM/RTY(+µ)|**partial**|NQ|1.32|2459|—|ES=partial (PF 1.29@0.5pt, **0.92@1pt** slip-fragile, corr 0.12); **YM/RTY = untested, NO DATA**|
|3|Timeframe|1/3/5/15/30m|**untested**|—|—|—|—|zone-based (opening range); TF sweep never run|
|4|Session|Lon/NYopen/lunch/aft/ON|**deployed**|NY-open|1.32|2459|n-a|other windows untested for ORB|
|5|Trigger|breakout/retest/pullback/mom|**partial**|breakout|1.32|2459|—|breakout=deployed; retest/pullback/momentum untested|
|6|OR length|5/15/30/60m|**partial**|15m(08:45-09:00)|1.32|2459|—|08:00-08:15 historically OOS 0.97; 5/30/60 not swept at 1pt|
|7|Stop|fixed/ATR/structure/BE-trail/step-trail|**deployed**|structure(range)|1.32|2459|n-a|trailing variants untested|
|8|Take-profit|fixedR/ATR/tiered/runner|**deployed**|4R fixed|1.32|2459|n-a|tiered-partials & runner untested|
|9|Max trades/day|1/2/unlimited|**deployed**|1|1.32|2459|n-a|2 & unlimited untested|
|10|Filters|vol/vol-regime/DoW/HTF/compression/SMT|**fail**|none|—|—|✗|**NR7 FAIL** (PF 1.08); **NR4 FAIL** (flat 1.30, dollars gutted 5×); **200SMA-regime FAIL**; **SMT FAIL** (no help); volume/vol-regime/DoW/HTF untested|

## DONCHIAN  (Stage-2 VALIDATED · PF 1.18 / net$ 7190 @3 MNQ · thin: drop-5 negative)
| # | Axis | Options | STATUS | Best | PF | net$ | S2 | Notes |
|---|------|---------|--------|------|----|----|----|-------|
|1|Entry side|long/short/both|**pass**|long-only|1.18|7190|✓|short & both untested — **with-trend shorts below 200SMA is a live hypothesis**|
|2|Instrument|NQ/ES/YM/RTY(+µ)|**partial**|NQ|1.18|7190|✓|ES=partial (PF 1.14, **corr 0.54 = half-redundant**); **YM/RTY untested, NO DATA**|
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
- **Cross-instrument reality:** only **ES tested** (ORB-ES marginal, slip-fragile at 1pt; Don-ES half-redundant corr 0.54). **GC / CL / YM / RTY = NO DATA on box — UNTESTED** (not "didn't transfer"; never run). Correction of prior assumption.
- **ORB filters that FAIL:** NR7, NR4, 200SMA-regime, SMT. Cutting trade count has not once raised ORB PF.

## RANKED HIGHEST-VALUE UNTESTED CELLS (real hypothesis, not grid-fill)
1. **RTY instrument (ORB + Donchian)** — Russell is materially *less* correlated to NQ than ES → a genuine fleet diversifier (bigger any-of-5 lift than any NQ tweak). **Needs Databento RTY/M2K 1m pull.** Highest ceiling.
2. **ORB timeframe sweep (3/5/15/30m)** — never swept; cheap; possible free PF or trade-count gain.
3. **Donchian short-side (with-trend shorts below 200SMA)** — currently long-only; adding regime-aligned shorts could ~2× coverage & trade count. Cheap.
4. **Donchian timeframe sweep (1/3/15/30m)** — cheap free-upside check.
5. **Breakout-RETEST trigger (ORB + Donchian)** — enter on pullback to the broken level instead of at break; better R:R hypothesis, may lift thin Donchian PF.
6. **ORB tiered-partials / runner TP** — capture trend-day extension beyond fixed 4R.
7. **Volume-confirmation filter (ORB + Donchian breakouts)** — filter false breakouts; the one filter family not yet tried on ORB.
8. **ORB max-2/day** — currently 1/day; a second qualified setup may add uncorrelated trades.

_Last updated: 2026-07-02._
