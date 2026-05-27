# Kronos Strategy Pipeline

How strategies go from idea to live trading and get evaluated automatically.

## Overview

```
Moon Dev Video → Strategy File → deploy_strategy.py → Live Engine
                                       ↓
                                 Auto-backtest (7d)
                                       ↓
                              Trade Journal tracks it
                                       ↓
                         Skill Updater discovers patterns
                                       ↓
                     strategy_tournament.py --review
                                       ↓
                         PROMOTED / DEMOTED / STANDBY
```

## Step 1: Write the Strategy

Start from the template:

```bash
cp strategies/TEMPLATE.py strategies/generated/my_new_strategy.py
```

Edit the file:
1. Set `name = "my_new_strategy"` and rename the class
2. Implement `_detect_entry()` with your entry logic
3. Adjust `default_params()` for your method's thresholds
4. Optionally add `PARAM_RANGES` for robustness testing

All parameters must use `self.get_param("key")` — never hardcode. This enables the self-tuning loop to adjust them later.

### Diagnostic Logging

The template includes built-in diagnostic logging every 12 candles (~1 hour on 5m). Add your key metrics to the DIAG line so you can see what the strategy "sees" in the engine logs:

```python
_log.info(f"DIAG #{self._diag_count}: close={candle.close:.0f} "
          f"my_indicator={value:.2f} liq={candle.liquidation_usd:.0f}")
```

## Step 2: Deploy

```bash
python3 scripts/deploy_strategy.py my_new_strategy
```

This will:
1. Find the strategy file in `strategies/*/`
2. Validate it (inherits BaseStrategy, has on_candle, uses get_param)
3. Run a 7-day backtest on existing candle data (no API calls)
4. Show you the results: trades, return, win rate, profit factor
5. Add it to the engine's `--strategy` list
6. Restart the engine
7. Log the deployment to `strategy_lifecycle` table

Skip the backtest with `--skip-backtest`. Preview with `--dry-run`.

## Step 3: Monitor

Once deployed, the strategy runs alongside existing strategies. The self-improving loop handles everything automatically:

- **Trade Journal** (`data/trade_journal.db`) — logs every entry and exit with full context (regime, signal strength, slippage, candle data)
- **Skill Updater** (runs every 6 hours) — analyzes performance, discovers patterns (bad regimes, bad hours, consecutive losses), writes recommendations
- **Skill File** (`skills/strategy_performance.md`) — human-readable report of all strategy stats
- **Regime Selector** — gates signals based on win rate per market regime
- **Parameter Self-Tuner** — adjusts stop loss, take profit, max hold based on trade data

Check strategy status any time:

```bash
# Quick scan of all strategies
python3 scripts/strategy_tournament.py --scan

# Backtest evaluation of undeployed strategies
python3 scripts/strategy_tournament.py --evaluate

# Check if live strategies are ready for promotion/demotion
python3 scripts/strategy_tournament.py --review
```

## Step 4: Review

After a strategy accumulates **20 trades OR 14 days** (whichever comes first), it's ready for review:

```bash
python3 scripts/strategy_tournament.py --review
```

### Promotion Criteria
- Win rate >= 40%
- Profit factor >= 1.0
- At least 20 trades

### Demotion Criteria
- Win rate < 30% after 20+ trades
- Max drawdown > 10% of allocation

### Standby
- Fewer than 20 trades after 14 days = not enough signals
- Consider loosening parameters (lower entry thresholds, wider lookback)

## Step 5: Remove (if needed)

```bash
python3 scripts/remove_strategy.py my_new_strategy --reason "poor win rate"
```

This removes it from the engine and logs the demotion. The strategy file is preserved for future re-evaluation with different parameters.

## Strategy Lifecycle Table

All transitions are tracked in `data/trade_journal.db`:

```sql
SELECT strategy_name, stage, reason, created_at
FROM strategy_lifecycle
ORDER BY created_at DESC;
```

Stages: `CANDIDATE` → `TESTING` → `PROMOTED` / `DEMOTED` / `STANDBY`

## File Locations

| File | Purpose |
|------|---------|
| `strategies/TEMPLATE.py` | Clean starting point for new strategies |
| `strategies/generated/` | AI-generated and Moon Dev adaptations |
| `strategies/momentum/` | Hand-curated momentum strategies |
| `strategies/reversal/` | Hand-curated reversal strategies |
| `scripts/strategy_tournament.py` | Lifecycle management (scan/evaluate/review) |
| `scripts/deploy_strategy.py` | Deploy strategy to live engine |
| `scripts/remove_strategy.py` | Remove strategy from live engine |
| `skills/strategy_performance.md` | Auto-generated performance report |
| `data/trade_journal.db` | Trade history + lifecycle tracking |

## Configurable Thresholds

Edit the `CONFIG` dict at the top of `scripts/strategy_tournament.py`:

```python
CONFIG = {
    "backtest_days": 7,
    "min_signals_7d": 1,
    "min_trades_for_review": 20,
    "min_days_for_review": 14,
    "promote_win_rate": 40.0,
    "promote_profit_factor": 1.0,
    "demote_win_rate": 30.0,
    "demote_max_dd_pct": 10.0,
}
```
