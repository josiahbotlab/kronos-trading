# MNQ London + Overnight Backtest

**Data**: yfinance stitched (~7 × 7-day windows) — MNQ=F: 23,918 candles, ES=F: 23,915 candles
**Period**: 2026-04-22 → 2026-05-15
**Sessions tested**: London KZ (03:00-05:00 ET) + Overnight (outside 05:00-17:00 ET)
**Regime**: Variant A (1h+4h SMA20>SMA50 on MNQ)
**SMT pair**: MNQ vs ES (not QQQ vs SPY)

## Results

| Metric | Value |
|---|---:|
| Trades | 27 |
| WR | 81.5% |
| PF | 0.81 |
| Trades/day | 2.45 |
| Return | -0.32% |

## By Session

- **overnight**: 22 trades · WR 77.3% · PF 0.54 · ret -0.77%
- **london**: 5 trades · WR 100.0% · PF inf · ret +0.45%
