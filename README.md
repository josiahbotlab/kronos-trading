# kronos-trading

Multi-strategy crypto trading system. Collects market and liquidation data, backtests strategies against historical SQLite data, runs them live in paper mode against a real-time price/liquidation feed, and tunes their parameters automatically based on closed-trade outcomes. Also includes a research module that pulls strategy ideas from YouTube transcripts via an LLM and feeds them into the backtest pipeline.

Currently runs against Coinbase Advanced Trade (price + execution) and Binance/Bybit (forced-liquidation feeds). Single-account paper trading; live execution wiring exists but is gated behind `paper=true`.

## Tech stack

- **Python 3.12** — asyncio for the websocket collectors and live engine, threads for the Telegram poster.
- **SQLite** (aiosqlite + sqlite3 stdlib) — every subsystem persists to its own DB in `data/`: `prices.db`, `liquidations.db`, `positions.db`, `trade_journal.db`, `execution.db`, `incubation.db`, `paper_trades.db`, `portfolio.db`, `risk.db`, `dryrun.db`, `market_data.db`.
- **ccxt** — Coinbase Advanced Trade and Binance public-data clients.
- **websockets** — direct subscriptions to `wss://fstream.binance.com/ws/!forceOrder@arr` and `wss://stream.bybit.com/v5/public/linear` (`allLiquidation.BTCUSDT`).
- **numpy / pandas** — backtester math, robustness/Monte-Carlo, strategy indicators.
- **Moonshot Kimi K2.5** (`https://api.moonshot.ai/v1`) — LLM for the research pipeline (transcript → structured strategy spec). Kimi K2.5 only accepts `temperature=1`, so the client omits the param.
- **yt-dlp** — pulls auto-generated subtitles from `@MoonDevOnYT`. YouTube datacenter-IP blocks mean this is run locally and the resulting `.txt` transcripts are rsynced into `research/cache/transcripts/manual/`.
- **Telegram Bot API** — alerts (no external lib, raw `urllib`).
- **systemd user units** — `kronos-prices.service`, `kronos-liquidations.service`, `kronos-positions.service`, `kronos-engine.service`, `moondev-monitor.{service,timer}`.

## Architecture

```
                   Coinbase pub        Binance / Bybit WS
                       |                       |
                       v                       v
              collectors/price_      collectors/liquidation_
              collector.py           collector.py
                       |                       |
                       v                       v
                  data/prices.db        data/liquidations.db
                       |                       |
                       +-----------+-----------+
                                   |
                                   v
                       execution/live_engine.py
                       (warmup -> per-candle loop)
                                   |
                  +----------------+-----------------+
                  |                |                 |
                  v                v                 v
            strategies/*    execution/risk_   execution/position_
            (Signal)        manager.py         manager.py
                                   |
                                   v
                       execution/coinbase_executor.py
                       (paper=true by default)
                                   |
                                   v
                       execution/trade_journal.py
                       (closed_trades -> data/trade_journal.db)
                                   |
                                   v
                       scripts/skill_updater.py
                       (parameter_recommendations,
                        skills/strategy_performance.md)
                                   |
                                   v
                       live_engine._apply_pending_params()
                       (clamped, manual-optima-gated)


                Research side-channel:
                    YouTube (@MoonDevOnYT) --[yt-dlp local]-->
                    research/cache/transcripts/manual/  -->
                    research/strategy_extractor.py (Moonshot) -->
                    research/research.db                      -->
                    research/evaluate_extracted.py            -->
                    strategies/generated/*.py                 -->
                    scripts/deploy_strategy.py
```

Key components:

- **collectors/price_collector.py** — ccxt Coinbase OHLCV poll, multi-symbol, multi-timeframe (5m / 15m / 1h / 4h / 6h / 1d). Symbols are dash-format (`BTC-USD`); the engine maps to Binance `BTCUSDT` only when joining liquidation rows. Backfills 90 days on first run, then incremental.
- **collectors/liquidation_collector.py** — dual websocket subscriber. Filters BTC perp, drops events below $10k notional, writes to `data/liquidations.db` (column `timestamp_ms`). Posts a daily Telegram digest plus a per-event alert when single liquidation ≥ $1M. The schema has a `cascade_1m` view and indexes on `timestamp_ms`, `usd_value`, `side`, plus `idx_liq_exchange_time`.
- **collectors/position_collector.py** — long/short ratio scraper, mostly informational.
- **core/backtester.py** — loads OHLCV + joined liquidation enrichment, walks each candle through a `BaseStrategy`, simulates entries/exits with a 6 bps taker fee assumption, emits a `PerformanceReport` (sharpe, sortino, max DD, win rate, profit factor, expectancy). Sweeps for live trades use the same engine.
- **core/robustness.py** — Monte-Carlo trade-order shuffles, parameter-perturbation sweeps, walk-forward windows.
- **execution/live_engine.py** — the production loop. Loads strategy class by name from `strategies/{momentum,reversal,generated}/`, polls `prices.db` for new candles, enriches with the last liquidation window, calls `strategy.on_candle()`, routes the signal through `RiskManager` and `PositionManager`, and writes the trade to `trade_journal.db`. Applies pending parameter changes from `parameter_recommendations` at startup.
- **execution/coinbase_executor.py** — JWT-auth Coinbase Advanced Trade client, paper mode by default with 5 bps slippage simulation.
- **execution/risk_manager.py** — portfolio-level kill-switch, per-strategy budget, max-drawdown, max-leverage, Kelly-fractioned position sizing.
- **execution/trade_journal.py** — closed-trade store; the source of truth for the self-tuner.
- **scripts/skill_updater.py** — reads `closed_trades`, segments by strategy, computes per-bucket performance, mines parameter patterns. Writes `skills/strategy_performance.md` (human-readable) and inserts rows into `parameter_recommendations` (status `pending`). Hard ceiling: a `PARAM_MANUAL_OPTIMA` dict caps each parameter so the tuner can only tighten below the manual optimum, never loosen above it. Mirrors of that dict live in both `skill_updater.py` and `live_engine.py`.
- **execution/live_engine.py::_apply_pending_params()** — at startup, applies pending recommendations, clamps each change to current ±20%, and refuses to cross the manual-optima ceiling.
- **research/** — `transcript_scanner.py` (yt-dlp), `manual_ingest.py` (watch dir for hand-curated transcripts), `strategy_extractor.py` (Moonshot Kimi K2.5 → structured strategy spec), `evaluate_extracted.py` (generate Python from spec, backtest, robustness, ship). The auto-generated strategies are generic and almost always need manual tuning before they're useful.

### Liquidation data feed status

The liquidation feed has a known production issue and **strategies that read liquidation features must gate on data freshness** — see [Status](#status--scope) below. Don't read this README and assume the data flow above is silently healthy.

## Running it locally

```bash
git clone git@github.com:josiahbotlab/kronos-trading.git
cd kronos-trading

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Bootstrap the runtime config
cp config/kronos.json.example config/kronos.json
# Edit config/kronos.json: paste Coinbase API key/secret, Telegram bot token+chat id
# OR set them as env vars (see below) — env vars override config file values
```

Common commands:

```bash
# Backfill 90d of OHLCV for the configured symbol set
python collectors/price_collector.py --backfill 90 --once

# Run the liquidation collector (long-running)
python collectors/liquidation_collector.py

# Backtest a single strategy
python scripts/run_strategy.py cascade_ride --symbol BTC-USD --timeframe 1h

# Backtest with robustness suite (Monte-Carlo + param sweep + walk-forward)
python scripts/run_strategy.py liq_bb_combo --symbol BTC-USD --timeframe 5m --robust

# Compare all registered strategies on one symbol
python scripts/run_strategy.py --compare --symbol BTC-USD --timeframe 1h

# Run the live (paper) engine
python execution/live_engine.py \
    --strategy liq_bb_combo \
    --symbol BTC-USD \
    --timeframe 5m \
    --capital 1000

# Multi-strategy live engine
python execution/live_engine.py \
    --strategy capitulation_reversal,vwap_mean_reversion,timeality \
    --symbol BTC-USD \
    --timeframe 5m

# Status check (does not start a loop)
python execution/live_engine.py --status

# Regenerate skill file + parameter recommendations from closed_trades
python scripts/skill_updater.py
python scripts/skill_updater.py --force --dry-run   # 0-trade test mode

# Deploy a new strategy file into the engine rotation
python scripts/deploy_strategy.py strategies/generated/parabolic_short.py

# Research pipeline (LLM strategy extraction)
python -m research.manual_ingest --watch                 # ingest hand-curated transcripts
python -m research.strategy_extractor                    # transcripts -> research.db
python research/evaluate_extracted.py --generate         # spec -> .py in strategies/generated/
python research/evaluate_extracted.py --backtest --robustness --telegram
```

On the VPS, the same commands run under systemd:

```bash
systemctl --user status kronos-prices kronos-liquidations kronos-engine
journalctl --user -u kronos-engine -f
bash scripts/deploy.sh        # code-only sync + restart
bash scripts/deploy_to_vps.sh # full deploy with secrets
```

## Environment variables

The runtime reads these from the process environment (`~/.config/environment.d/kronos.conf` on the VPS) and falls back to `config/kronos.json` where applicable. Env vars win.

| Variable | Purpose | Read by |
|---|---|---|
| `COINBASE_API_KEY` | Coinbase Advanced Trade API key | `execution/coinbase_connector.py`, `execution/coinbase_executor.py` |
| `COINBASE_API_SECRET` | Coinbase Advanced Trade API secret (PEM private key) | same |
| `KRONOS_TG_BOT_TOKEN` | Telegram bot token for live alerts | `execution/telegram_notifier.py` |
| `KRONOS_TG_CHAT_ID` | Telegram chat or channel id | same |
| `MOONSHOT_API_KEY` | Moonshot/Kimi API key for the research extractor | `research/kimi_client.py`, `research/strategy_extractor.py` |
| `ALPACA_API_KEY` | Alpaca data API (used only by `strategies/augxmented/` for equities backtests) | `strategies/augxmented/backtester/fetch_data.py` |
| `ALPACA_SECRET_KEY` | Alpaca secret | same |
| `ALPACA_PAPER` | `"true"`/`"false"` — selects Alpaca paper vs live data endpoint | same |

`COINBASE_API_KEY` / `COINBASE_API_SECRET` can also be passed as `$1 $2` to `scripts/deploy_to_vps.sh`.

## Status / scope

**Engine rotation** (`config/kronos.json` → `engine.strategies`, as of 2026-05-08):

- `capitulation_reversal`
- `vwap_mean_reversion`
- `mtf_mean_reversion`
- `timeality`
- `liq_mean_rev_adx`

These run on `BTC-USD` 5m by default. Capital, max-drawdown, and risk-per-trade come from `config/kronos.json::risk`.

**Liquidation data freshness — known issue, do not skip:**

The liquidation feed is partially broken in production.

- Binance `!forceOrder@arr` — last wrote on **2026-02-19**. Binance Futures USD-M moved or restricted the public unauthenticated stream; reconnects succeed but no events arrive.
- Bybit `allLiquidation.BTCUSDT` — currently writing (last event seen 2026-05-08). The old `liquidation.BTCUSDT` topic returns `error: handler not found` (deprecated March 2025) and must not be re-introduced.

Because the `>$10k` filter already produces long silent stretches during quiet markets, "no rows for N minutes" is ambiguous. **Any strategy that consumes liquidation features must check `liq_data_fresh`** — a boolean the backtester and live engine attach to each enrichment, based on `now() - max(timestamp_ms) < threshold` (typically 5-10 minutes). When `not liq_data_fresh`, the strategy must return `Signal(direction=None)` rather than treating absence as zero. `liq_mean_rev_adx` is the main consumer today.

**Self-tuning safety:**

`scripts/skill_updater.py` writes parameter recommendations into `parameter_recommendations` with `status=pending`. `live_engine.py::_apply_pending_params()` applies them on next startup, clamps to ±20% per cycle, and refuses to loosen any parameter past the value listed in the `PARAM_MANUAL_OPTIMA` dict. That dict is mirrored in both `skill_updater.py` and `live_engine.py` — keep them in sync. This guard exists because the tuner previously walked thresholds outward off a stale loosened baseline read from `parameter_changes`.

**Scope notes:**

- `paper=true` is the default in `coinbase_executor.py`. Real-money execution requires explicitly setting it false and providing live Coinbase credentials.
- `strategies/generated/` contains ~360 auto-generated strategies from the LLM research pipeline. The vast majority are not production-ready and only the names listed in `engine.strategies` above are live.
- The price collector covers 20+ symbols, but the live engine currently trades BTC-USD only.
- Hyperliquid and ccxt-futures execution paths exist in `execution/exchange_connector.py` history but are not active. Coinbase is the only routed exchange.
