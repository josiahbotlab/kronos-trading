# Funded-Income Analysis — two-firm path

_Session 2026-07-02/03. All pass-rate & income figures are SIM RESULTS from this session (bootstrap, seed 42, 10k windows). Firm-rule facts labeled as such._

> ⚠️ **FIGURES NEED REBUILD (flagged 2026-07-03).** Every pass-rate and income number below was computed from the ORB-15m-trail daily-net pool (`orb_15m_trail_v1.json`), which was built on the **inflated** run (implied WR 69% / PF 6.04). The committed/reproducible ORB-15m-trail is **WR 52.2% / PF 4.46 / avgR +2.26** (`backtest_orb_15m_trail_oos.py`). The favorable-fill inflation flows through the pool into the bootstrap, so the **58.58% combine pass-rate and the $3.3–4.0k/mo income figures are overstated and must be rebuilt against an honest pool before use.** Do not act on the income numbers until rebuilt.

## Validated lineup
- **ORB-15m-trail (2 MNQ) + Donchian-long (3 MNQ)** — KZ-free, both NQ. Costs $1.24/RT + 1.0pt slip.
- ORB-15m-trail pool: `pools/orb_15m_trail_v1.json` · 360 trades · sha256 `acade2c7f7be50cbdcd4551c3034810e0e2d3558cb4ed4526c390176f05a8775` (git-committed 4104ba1) — **⚠️ built on the inflated run (implies WR 69%/PF 6.04); committed backtest = WR 52.2%/PF 4.46. This pool's daily-net feeds the income sim, so the figures below are overstated and need a rebuild.**
- Donchian-long: 379 trades (reconstructed from `nq_1m_db`, N=12/5m/max-1/200SMA/1.5ATR/2R)
- Canonical baseline: `baseline_800_v4.json` sha256 `615e9414ce0db99d3864f7f4a443a61488c6dc0391fd7150c5e72537db098b12`
- Both strategies Stage-2 validated with realistic 1m-resolved fills (see STRATEGY_REGISTRY.md / TEST_MATRIX.md).

## Combine / evaluation pass rates (getting funded)
| venue | any-of-5 | notes |
|---|---|---|
| **TopStep combine** | **58.58%** | 30-day window, +$3k / $48k static floor / −$800 halt (cb.any_of_5, v4) |
| **LucidFlex eval** | **~100%** | 89.12% single-acct; median 64 days to pass; 10.7% blow the $2k trailing before target |

- **LucidFlex eval is far easier — the decisive reason is NO TIME LIMIT** (grind to $3k over months vs TopStep's 30-day clock).
- **50% consistency rule is a minor speed bump:** only **~11%** of accounts get blocked at $3k (biggest day > 50% of profit); of those **99.4% grind past in a median +5 days**, only 0.3% blow out grinding. Profit spread over ~64 days means no single trail-day dominates 50% of the cumulative.

## Funded income (5 accounts, monthly net after split)
| firm · policy | 5-acct/mo | 10-acct/mo | death (90d) | verdict |
|---|---|---|---|---|
| TopStep greedy | $3,402 | $6,804 | **55%** | ❌ NEVER USE — dominated |
| **TopStep +$1500 buffer** | $3,349 | $6,699 | **14%** | ✅ near-free 4× survival win |
| **LucidFlex greedy** | **$4,040** | **$8,081** | 33% | ✅ income ceiling |
| LucidFlex +$1000 buffer | $3,824 | $7,647 | 26% | ✅ balanced |
| LucidFlex +$1500 buffer | $3,377 | $6,755 | 15% | ✅ durable |
| LucidFlex +$2000 buffer | $2,841 | $5,682 | 10% | conservative |

- **TopStep buffer is a near-free 4× survival win** (death 55%→14% for −1.5% income) — TopStep-SPECIFIC, because it counters the post-payout **MLL-reset-to-$0** death mechanic.
- **LucidFlex buffer is a LINEAR income/survival tradeoff** (no reset mechanic to counter) — each $500 of buffer buys ~6–17pp less death for ~$200–660/mo less income.
- Payout cap $2k barely matters vs $5k: 50%-of-balance almost always binds first.

## Key structural facts (FIRM RULES — user-verified 2026, not sim output)
- **LucidFlex caps at 5 funded accounts per household** (hard ceiling).
- LucidFlex new accounts: **90/10 from $1** (100%-first-$10k only for pre-2025-11-28 accounts).
- **Both firms ban cross-account hedging.**
- **TopStep MLL resets to $0 after each payout** (death trap); **LucidFlex MLL locks at start, no reset** — this is WHY LucidFlex out-earns end-to-end.
- Payout cap **$2,000/request** both firms; 50%-of-balance usually binds first.
- Both firms **allow automated trading.**

## Best strategy — run both firms, 5 + 5
- **Primary: LucidFlex** — greedy ($4,040/5-acct, 33% death) or +$1000 buffer ($3,824, 26%).
- **Secondary: TopStep +$1500 buffer** ($3,349/5-acct, 14% death).
- **Combined ~$7,000–7,400/mo across 10 accounts** (e.g., LucidFlex greedy $4,040 + TopStep buffered $3,349 = **$7,389/mo**).
- **$10k/mo goal needs a third firm or a stronger/additional edge** — two firms × 5 accounts caps out around $7.4k/mo with this lineup.

## Methodology / assumptions (all figures)
- Bootstrap: 10,000 windows, days sampled with replacement from the combined daily-net pool (0-filled weekdays), **seed 42**; monthly = 90-day total ÷ 3.
- Death evaluated on END-OF-DAY balance vs trailing floor (floor = peak_EOD − $2000, locks static $0 once peak ≥ $2000).
- TopStep post-payout floor resets to $0; LucidFlex does not.
- Splits applied as stated (TopStep 100%-first-$10k then 90/10; LucidFlex 90/10 from $1).
- Withdraw at 5 winning/profitable days per cycle (TopStep win day = net ≥ $150; LucidFlex profitable day = net > $0 [assumed, no threshold given]); LucidFlex min payout $500, max 6 payouts then graduate.
- **Income EXCLUDES account/activation cost and reset/reactivation fees; dead accounts not reactivated within window; accounts modeled independent (no cross-account correlation).**
- Intraday drawdown not modeled (EOD-only), per the EOD-trailing rule.

_Last updated: 2026-07-03. ⚠️ ORB-15m-trail figures corrected (WR 52.2%/PF 4.46/avgR +2.26, was 69%/6.04 from uncommitted orb_oos.py); pass-rate & income numbers built on the inflated pool and NOT yet rebuilt._
