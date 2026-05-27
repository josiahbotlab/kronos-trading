#!/usr/bin/env python3
"""Final tournament of all profitable strategies."""
import sys
sys.path.insert(0, ".")
from core.backtester import Backtester

results = []

# 1. Timeality (optimized)
from strategies.generated.timeality import Timeality
bt = Backtester("BTC-USD", "5m")
r = bt.run(Timeality())
results.append(("Timeality", r))

# 2. Liq Mean Rev ADX
from strategies.generated.liq_mean_rev_adx import LiqMeanRevADX
bt = Backtester("BTC-USD", "5m")
r = bt.run(LiqMeanRevADX())
results.append(("Liq Mean Rev ADX", r))

# 3. Research 130 (tuned contrarian)
from strategies.generated.research_130_liquidation_based_contrarian_strategy import Research130LiquidationBasedContrarianStrategy
bt = Backtester("BTC-USD", "5m")
r = bt.run(Research130LiquidationBasedContrarianStrategy())
results.append(("Research 130 Contrarian", r))

# 4. Research 303 (tuned momentum)
from strategies.generated.research_303_liquidation_based_momentum import Research303LiquidationBasedMomentum
bt = Backtester("BTC-USD", "5m")
r = bt.run(Research303LiquidationBasedMomentum())
results.append(("Research 303 Momentum", r))


def grade(r):
    score = 0
    if r.total_return_pct > 5: score += 3
    elif r.total_return_pct > 2: score += 2
    elif r.total_return_pct > 0: score += 1
    if r.win_rate_pct > 60: score += 2
    elif r.win_rate_pct > 50: score += 1
    if r.profit_factor > 2: score += 3
    elif r.profit_factor > 1.5: score += 2
    elif r.profit_factor > 1: score += 1
    if r.sharpe_ratio > 2: score += 2
    elif r.sharpe_ratio > 1: score += 1
    if r.max_drawdown_pct > 15: score -= 2
    elif r.max_drawdown_pct > 10: score -= 1
    if r.total_trades >= 15: score += 1
    return score


print("=" * 105)
print(f"{'Strategy':30s} | Grade | Score | Trades |  Return |    WR |    PF |  Sharpe |  MaxDD")
print("-" * 105)

grade_map = {8: "A", 7: "B+", 6: "B", 5: "C+", 4: "C", 3: "D+", 2: "D"}

for name, r in sorted(results, key=lambda x: x[1].total_return_pct, reverse=True):
    s = grade(r)
    g = grade_map.get(s, "A" if s >= 8 else "F")
    print(f"{name:30s} | {g:>5s} |   {s:3d} | {r.total_trades:6d} | {r.total_return_pct:+6.2f}% | {r.win_rate_pct:5.1f}% | {r.profit_factor:5.2f} | {r.sharpe_ratio:6.2f} | {r.max_drawdown_pct:5.2f}%")

print("=" * 105)
