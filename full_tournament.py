#!/usr/bin/env python3
"""Full tournament of all strategies."""
import sys
sys.path.insert(0, ".")
from core.backtester import Backtester

results = []

# === PROVEN STRATEGIES ===
from strategies.generated.timeality import Timeality
bt = Backtester("BTC-USD", "5m")
r = bt.run(Timeality())
results.append(("Timeality", r, "temporal", "hand-coded #326"))

from strategies.generated.liq_mean_rev_adx import LiqMeanRevADX
bt = Backtester("BTC-USD", "5m")
r = bt.run(LiqMeanRevADX())
results.append(("Liq Mean Rev ADX", r, "mean_rev", "hand-coded #34"))

from strategies.generated.research_130_liquidation_based_contrarian_strategy import Research130LiquidationBasedContrarianStrategy
bt = Backtester("BTC-USD", "5m")
r = bt.run(Research130LiquidationBasedContrarianStrategy())
results.append(("R130 Contrarian", r, "contrarian", "tuned #130"))

from strategies.generated.research_303_liquidation_based_momentum import Research303LiquidationBasedMomentum
bt = Backtester("BTC-USD", "5m")
r = bt.run(Research303LiquidationBasedMomentum())
results.append(("R303 Momentum", r, "momentum", "tuned #303"))

# === NEW FROM DB (this session) ===
from strategies.generated.bb_squeeze_adx import BBSqueezeADX
s = BBSqueezeADX()
s._params["kc_atr_mult"] = 1.0
s._params["adx_threshold"] = 15
s._params["take_profit_pct"] = 2.0
s._params["stop_loss_pct"] = 1.5
bt = Backtester("BTC-USD", "5m")
r = bt.run(s)
results.append(("BB Squeeze ADX*", r, "breakout", "hand-coded #163 (opt)"))

from strategies.generated.zscore_stat_arb import ZScoreStatArb
bt = Backtester("BTC-USD", "5m")
r = bt.run(ZScoreStatArb())
results.append(("Z-Score Stat Arb", r, "mean_rev", "hand-coded #292"))

from strategies.generated.gap_go_uo import GapGoUO
bt = Backtester("BTC-USD", "5m")
r = bt.run(GapGoUO())
results.append(("Gap Go UO", r, "momentum", "hand-coded #165"))

# === NEW FROM TRANSCRIPTS ===
from strategies.generated.markov_down_bars import MarkovDownBars
bt = Backtester("BTC-USD", "5m")
r = bt.run(MarkovDownBars())
results.append(("Markov Down Bars", r, "mean_rev", "new transcript"))

from strategies.generated.vwap_adx_trend import VwapAdxTrend
bt = Backtester("BTC-USD", "5m")
r = bt.run(VwapAdxTrend())
results.append(("VWAP ADX Trend", r, "trend", "new transcript"))


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


grade_map = {10: "A+", 9: "A", 8: "A-", 7: "B+", 6: "B", 5: "C+", 4: "C", 3: "D+", 2: "D", 1: "D-", 0: "F"}

print()
print("=" * 135)
print(f"{'Strategy':22s} | {'Source':28s} | {'Cat':10s} | Grade | Sc | Trades | Return  |   WR   |   PF  | Sharpe |  MaxDD")
print("-" * 135)

for name, r, cat, src in sorted(results, key=lambda x: x[1].total_return_pct, reverse=True):
    s = grade(r)
    g = grade_map.get(s, "A+" if s >= 10 else "F")
    print(f"{name:22s} | {src:28s} | {cat:10s} | {g:>5s} | {s:2d} | {r.total_trades:6d} | {r.total_return_pct:+6.2f}% | {r.win_rate_pct:5.1f}%  | {r.profit_factor:5.2f} | {r.sharpe_ratio:6.2f} | {r.max_drawdown_pct:5.2f}%")

print("=" * 135)
print()
print("* BB Squeeze ADX optimized: kc_atr_mult=1.0, adx_threshold=15 — only 9 trades, not statistically significant")
print()

profitable = sum(1 for _, r, _, _ in results if r.total_return_pct > 0)
print(f"Profitable: {profitable}/{len(results)}")
