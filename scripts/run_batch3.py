#!/usr/bin/env python3
"""
Batch 3 Strategy Evaluation
"""
import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.backtester import Backtester
from core.robustness import RobustnessTestSuite
from strategies.templates.base_strategy import BaseStrategy

STRATEGIES = [
    ("strategies/generated/adx_macd_momentum.py", "AdxMacdMomentum"),
    ("strategies/generated/adx_rising_macd.py", "AdxRisingMacd"),
    ("strategies/generated/bollinger_bands_capitulation_filter.py", "BollingerBandsCapitulationFilter"),
    ("strategies/generated/capitulation_reversal.py", "CapitulationReversal"),
    ("strategies/generated/hlp_sentiment_z_score_reversal.py", "HlpSentimentZScoreReversal"),
]

PROJECT_ROOT = Path(__file__).parent.parent


def load_strategy(filepath, class_name):
    full_path = PROJECT_ROOT / filepath
    spec = importlib.util.spec_from_file_location(class_name, full_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    cls = getattr(mod, class_name)
    param_ranges = getattr(mod, "PARAM_RANGES", None)
    return cls, param_ranges


def main():
    print("\n" + "=" * 70)
    print("  KRONOS BATCH 3 STRATEGY EVALUATION")
    print("  5 strategies | BTC-USD 1h | 90 days")
    print("=" * 70)

    results = []

    for filepath, class_name in STRATEGIES:
        strategy_cls, param_ranges = load_strategy(filepath, class_name)
        strat = strategy_cls()
        name = strat.name

        print(f"\n{'─' * 60}")
        print(f"  {name} ({class_name})")
        print(f"{'─' * 60}")

        bt = Backtester(
            symbol="BTC-USD",
            timeframe="1h",
            initial_capital=10000.0,
            use_liquidation_data=True,
        )

        try:
            report = bt.run(strat)
        except Exception as e:
            print(f"  BACKTEST FAILED: {e}")
            import traceback
            traceback.print_exc()
            results.append({"name": name, "class": class_name, "error": str(e)})
            continue

        ret = report.total_return_pct
        dd = report.max_drawdown_pct
        sharpe = report.sharpe_ratio
        trades = report.total_trades
        wr = report.win_rate_pct
        pf = report.profit_factor

        print(f"  Return:    {ret:+.2f}%")
        print(f"  Max DD:    {dd:.2f}%")
        print(f"  Sharpe:    {sharpe:.2f}")
        print(f"  Trades:    {trades}")
        print(f"  Win Rate:  {wr:.1f}%")
        print(f"  PF:        {pf:.2f}")

        result = {
            "name": name,
            "class": class_name,
            "return_pct": ret,
            "max_dd_pct": dd,
            "sharpe": sharpe,
            "trades": trades,
            "win_rate": wr,
            "profit_factor": pf,
        }

        if ret > 0 and trades >= 5:
            print(f"\n  Running robustness suite...")
            try:
                suite = RobustnessTestSuite(bt, strategy_cls)
                robust = suite.run_all(
                    param_ranges=param_ranges,
                    n_monte_carlo=50,
                    n_walk_windows=4,
                )
                result["robustness"] = {
                    "passed": robust.tests_passed,
                    "total": robust.tests_total,
                    "overall_pass": robust.overall_pass,
                    "summary": robust.summary(),
                }
                print(f"  Robustness: {robust.tests_passed}/{robust.tests_total} "
                      f"{'PASS' if robust.overall_pass else 'FAIL'}")
                print(f"  {robust.summary()}")
            except Exception as e:
                print(f"  ROBUSTNESS FAILED: {e}")
                import traceback
                traceback.print_exc()
                result["robustness"] = {"error": str(e)}
        elif trades < 5:
            print(f"  Skipping robustness: too few trades ({trades})")
            result["robustness"] = {"skipped": "too few trades"}
        else:
            print(f"  Skipping robustness: not profitable ({ret:+.2f}%)")
            result["robustness"] = {"skipped": "not profitable"}

        results.append(result)

    # Summary
    print(f"\n{'=' * 70}")
    print("  BATCH 3 SUMMARY")
    print(f"{'=' * 70}")
    print(f"\n{'Strategy':<36} {'Return':>8} {'DD':>8} {'Sharpe':>8} {'Trades':>7} {'WR':>6} {'Robust':>10}")
    print("-" * 88)
    for r in results:
        if "error" in r:
            print(f"{r['name']:<36} ERROR: {r['error'][:40]}")
            continue
        robust_str = "—"
        rob = r.get("robustness", {})
        if "passed" in rob:
            robust_str = f"{rob['passed']}/{rob['total']}" + (" PASS" if rob['overall_pass'] else " FAIL")
        elif "skipped" in rob:
            robust_str = "skip"
        print(f"{r['name']:<36} {r['return_pct']:>+7.2f}% {r['max_dd_pct']:>7.2f}% "
              f"{r['sharpe']:>7.2f} {r['trades']:>7} {r['win_rate']:>5.1f}% {robust_str:>10}")

    # Save results
    out_path = PROJECT_ROOT / "strategies" / "generated" / "batch3_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Results saved to: {out_path}")

    # Send Telegram report
    try:
        from execution.telegram_notifier import TelegramNotifier
        tg = TelegramNotifier()
        lines = ["<b>KRONOS Batch 3 Evaluation</b>", ""]
        lines.append(f"<b>{'Strategy':<30} {'Ret':>7} {'Sharpe':>7} {'WR':>5} {'Robust':>8}</b>")
        for r in results:
            if "error" in r:
                lines.append(f"{r['name']:<30} ERROR")
                continue
            rob = r.get('robustness', {})
            rob_str = "—"
            if 'passed' in rob:
                rob_str = f"{rob['passed']}/{rob['total']} {'PASS' if rob['overall_pass'] else 'FAIL'}"
            elif 'skipped' in rob:
                rob_str = rob['skipped'][:10]
            emoji = '✅' if r.get('return_pct', 0) > 0 else '❌'
            lines.append(f"{emoji} {r['name'][:28]:<28} {r['return_pct']:>+6.1f}% {r['sharpe']:>6.2f} {r['win_rate']:>4.0f}% {rob_str}")
        
        profitable = [r for r in results if r.get('return_pct', 0) > 0 and 'error' not in r]
        robust_pass = [r for r in results if r.get('robustness', {}).get('overall_pass')]
        lines.append(f"\nProfitable: {len(profitable)}/{len(results)} | Robust: {len(robust_pass)}/{len(results)}")
        
        msg = "\n".join(lines)
        tg.send(msg)
        print("  Telegram report sent!")
    except Exception as e:
        print(f"  Telegram send failed: {e}")

    return results


if __name__ == "__main__":
    main()
