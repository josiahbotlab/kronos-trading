# Prop Firm Rules Reference (TopStep + Lucid)

Pulled 2026-07-02 from official help centers and current third-party rule trackers. Rules change often. Re-verify anything marked VERIFY against the live dashboard before wiring it into executor logic. Feeds the withdrawal-timing + risk-sizing + consistency layer.

## What changed since prior notes
- TopStep payout cap: was $5,000. Now ~$2,000 per request on 50K Standard path (cut late April 2026). Changes the withdrawal-cadence math.
- TopStep added its own per-contract commission 2026-04-12: ~$0.25/side micros, on top of exchange/clearing. Sims use $1.24/RT MNQ. Confirm $1.24 still covers all-in or bump it.
- TopStep consistency: does NOT apply to Standard-path payouts. The 50% figure is the Combine passing rule (best day <= 50% of profit target). Separate Consistency path has a 40% target. You are on Standard.
- TopStep split: current sign-ups 90/10 from $1. "100% of first $10K" grandfathered only for accounts opened before 2026-01-12. VERIFY per account.
- Lucid "50% consistency eval-only" confirmed correct.

## Side by side

| Item | TopStep 50K Standard (XFA) | Lucid LucidFlex 50K funded |
|---|---|---|
| Drawdown | EOD-trailing, locks at $0 after first payout | EOD-trailing, locks once past initial trail balance |
| MLL (50K) | Starts -$2,000, trails, locks $0 post-payout | Starts -$2,000 below start, EOD only |
| Daily loss limit | Combine only ($1,000/50K); XFA Standard none | None |
| Flat time | 3:10 PM CT | 4:45 PM ET |
| Overnight/weekend | No | No except LucidLive |
| Funded consistency | None on Standard | None funded (50% eval only) |
| Winning day | $150+ net, need 5 | Min profit on 5 days/cycle |
| Payout cap/request | ~$2,000 VERIFY, AND 50% of balance | Low thousands (~$2k) VERIFY, plus buffer |
| Buffer/reset | MLL resets $0 after every payout (death mechanic) | Buffer = MLL + $100; withdraw above buffer + initial |
| Split | 90/10 from $1 (100%-first-$10K grandfathered pre-2026-01-12) VERIFY | 90/10 |
| Payout speed | 1-3 business days | ~15 min |
| Household cap | Not household-capped | Hard cap 5 funded/household |
| Automation | Allowed, no HFT/scalp algos | Allowed, sub-5s microscalp >50% profit flagged |
| VPN | Prohibited | No cross-firm hedging either way |
| Code | n/a | DGT |

## Executor logic (JadeCap layer)
TopStep withdrawal: MLL resets $0 each payout, so post-payout you're one bad trade from breach. Sim showed a ~$1,500 buffer cut death 55% -> 14% for near-zero income loss. Keep it. Size each request as min(~$2,000, 50% of balance). $5k assumption dead; more small requests, not fewer big ones.

TopStep single-day: Standard path has no funded consistency freeze, so do NOT cap single-day P&L for payout eligibility on funded. 50% best-day rule only bites during the Combine.

Lucid sizing: no DLL, no funded consistency, constraint is purely EOD MLL. Buffer here is a linear tradeoff (drawdown doesn't reset on payout, unlike TopStep). Need 5 profitable days/cycle -> executor needs a min-profit-day counter. Cap low thousands, same small-frequent pattern.

Both: no cross-account hedging (critical at 5+5 on one signal). No VPN on TopStep. Model per-firm extraction ceiling / freeze risk.

## Third firm
Not pulled. Name it to add a column. Lucid's 5-funded household cap is a hard ceiling, so a third firm is the real lever past ~10 accounts.
