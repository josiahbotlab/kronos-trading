# Augxmented 1m Kill-Zone Backtest

**Data**: QQQ + SPY 1m from `data/market_data.db` (Alpaca IEX)
**Period**: 2026-04-09 → 2026-05-15 (27 trading days, 12,479 bars)
**Strategy**: AugxmentedStrategy with `_check_session` overridden for DST-aware kill-zone gate
**Kill zones (ET)**: London 03:00-05:00, NY open 09:30-11:30, NY pm 14:00-15:30
**1m-adjusted params**: max_hold_bars=240, cooldown_bars=30, min_history=1500 (others at defaults: min_score=13, bos_required=True)

## Results

| Metric | Value |
|---|---:|
| Trades | 71 |
| Win Rate | 93.0% |
| Profit Factor | 2.76 |
| Trades/day | 2.63 |
| Return (sum %) | +5.74% |
| Long / Short | 71 / 0 |

## IS / OOS 60/40 Split

- IS  (first 60%): 42 trades | WR 92.9% | PF 3.81 | 2.47/day | ret +3.47% | L/S 42/0
- OOS (last  40%): 29 trades | WR 93.1% | PF 2.12 | 2.64/day | ret +2.27% | L/S 29/0

## Exit Reason Breakdown

- `augx_exit_take_profit_tp3`: 66
- `augx_exit_max_hold_post_tp2`: 2
- `augx_exit_max_hold_post_tp1`: 1
- `augx_exit_trailing_stop`: 1
- `end_of_data`: 1

## Criteria

Target: trades/day >= 2.0 AND WR >= 65% AND PF >= 1.5

- trades/day 2.63 — PASS
- WR 93.0% — PASS
- PF 2.76 — PASS
- **OVERALL: PASS**

## Top Strategy Tags (signal-gen funnel)

- `augx_forbidden_session`: 4,405
- `augx_hold`: 3,072
- `augx_warmup`: 1,499
- `augx_no_bos`: 1,346
- `augx_cooldown`: 1,342
- `augx_htf_filter_short`: 482
- `augx_no_signal`: 192
- `augx_entry_long`: 71
- `augx_exit_take_profit_tp3`: 66
- `augx_exit_max_hold_post_tp2`: 2
- `augx_exit_max_hold_post_tp1`: 1
- `augx_exit_trailing_stop`: 1

## Trade List

                    entry                      exit  dir  entry_p  exit_p   pnl_pct  bars                      reason  score   win
2026-04-09 18:39:00+00:00 2026-04-09 19:09:00+00:00 LONG  608.580 609.305  0.001191    30   augx_exit_take_profit_tp3     16  True
2026-04-10 13:32:00+00:00 2026-04-10 17:32:00+00:00 LONG  612.740 610.070 -0.004357   240 augx_exit_max_hold_post_tp2     14 False
2026-04-10 18:20:00+00:00 2026-04-10 19:14:00+00:00 LONG  610.890 611.285  0.000647    54   augx_exit_take_profit_tp3     13  True
2026-04-13 13:49:00+00:00 2026-04-13 14:07:00+00:00 LONG  610.860 611.870  0.001653    18   augx_exit_take_profit_tp3     14  True
2026-04-13 14:44:00+00:00 2026-04-13 14:58:00+00:00 LONG  611.920 612.760  0.001373    14   augx_exit_take_profit_tp3     14  True
2026-04-13 18:45:00+00:00 2026-04-13 18:52:00+00:00 LONG  614.750 614.990  0.000390     7   augx_exit_take_profit_tp3     13  True
2026-04-13 19:23:00+00:00 2026-04-13 19:31:00+00:00 LONG  615.330 615.630  0.000488     8   augx_exit_take_profit_tp3     13  True
2026-04-14 13:30:00+00:00 2026-04-14 13:37:00+00:00 LONG  620.995 622.320  0.002134     7   augx_exit_take_profit_tp3     15  True
2026-04-14 14:09:00+00:00 2026-04-14 14:17:00+00:00 LONG  622.660 623.100  0.000707     8   augx_exit_take_profit_tp3     13  True
2026-04-14 14:54:00+00:00 2026-04-14 15:25:00+00:00 LONG  624.050 624.560  0.000817    31   augx_exit_take_profit_tp3     13  True
2026-04-14 19:06:00+00:00 2026-04-14 19:11:00+00:00 LONG  627.180 627.640  0.000733     5   augx_exit_take_profit_tp3     13  True
2026-04-15 13:30:00+00:00 2026-04-15 13:38:00+00:00 LONG  628.970 629.740  0.001224     8   augx_exit_take_profit_tp3     13  True
2026-04-15 14:14:00+00:00 2026-04-15 14:26:00+00:00 LONG  630.760 631.655  0.001419    12   augx_exit_take_profit_tp3     13  True
2026-04-15 14:56:00+00:00 2026-04-15 15:27:00+00:00 LONG  632.770 633.345  0.000909    31   augx_exit_take_profit_tp3     13  True
2026-04-15 18:31:00+00:00 2026-04-15 18:35:00+00:00 LONG  634.800 635.250  0.000709     4   augx_exit_take_profit_tp3     13  True
2026-04-15 19:06:00+00:00 2026-04-15 19:27:00+00:00 LONG  636.110 636.490  0.000597    21   augx_exit_take_profit_tp3     13  True
2026-04-16 14:37:00+00:00 2026-04-16 15:02:00+00:00 LONG  637.910 638.860  0.001489    25   augx_exit_take_profit_tp3     13  True
2026-04-16 18:36:00+00:00 2026-04-16 18:47:00+00:00 LONG  638.750 639.300  0.000861    11   augx_exit_take_profit_tp3     14  True
2026-04-17 14:00:00+00:00 2026-04-17 14:40:00+00:00 LONG  646.870 648.330  0.002257    40   augx_exit_take_profit_tp3     13  True
2026-04-17 18:25:00+00:00 2026-04-17 20:12:00+00:00 LONG  648.140 648.940  0.001234   103   augx_exit_take_profit_tp3     13  True
2026-04-20 15:21:00+00:00 2026-04-20 15:29:00+00:00 LONG  644.410 645.710  0.002017     8   augx_exit_take_profit_tp3     14  True
2026-04-20 18:07:00+00:00 2026-04-20 18:24:00+00:00 LONG  646.225 646.620  0.000611    17   augx_exit_take_profit_tp3     13  True
2026-04-20 18:54:00+00:00 2026-04-20 20:36:00+00:00 LONG  646.740 648.130  0.002149    79   augx_exit_take_profit_tp3     14  True
2026-04-21 14:00:00+00:00 2026-04-21 18:00:00+00:00 LONG  649.255 645.960 -0.005075   240 augx_exit_max_hold_post_tp2     13 False
2026-04-21 18:55:00+00:00 2026-04-21 19:03:00+00:00 LONG  646.000 646.540  0.000836     8   augx_exit_take_profit_tp3     14  True
2026-04-22 14:15:00+00:00 2026-04-22 14:30:00+00:00 LONG  651.610 652.620  0.001550    15   augx_exit_take_profit_tp3     13  True
2026-04-22 15:11:00+00:00 2026-04-22 15:24:00+00:00 LONG  652.490 652.880  0.000598    13   augx_exit_take_profit_tp3     13  True
2026-04-22 18:41:00+00:00 2026-04-22 18:47:00+00:00 LONG  653.560 653.830  0.000413     6   augx_exit_take_profit_tp3     13  True
2026-04-22 19:25:00+00:00 2026-04-22 19:50:00+00:00 LONG  654.350 654.860  0.000779    25   augx_exit_take_profit_tp3     13  True
2026-04-23 14:51:00+00:00 2026-04-23 14:57:00+00:00 LONG  654.610 655.650  0.001589     6   augx_exit_take_profit_tp3     13  True
2026-04-23 19:14:00+00:00 2026-04-23 19:58:00+00:00 LONG  650.800 651.665  0.001329    44   augx_exit_take_profit_tp3     13  True
2026-04-24 14:09:00+00:00 2026-04-24 15:03:00+00:00 LONG  658.960 660.715  0.002663    54   augx_exit_take_profit_tp3     13  True
2026-04-24 18:35:00+00:00 2026-04-24 19:09:00+00:00 LONG  663.330 663.850  0.000784    34   augx_exit_take_profit_tp3     14  True
2026-04-27 18:09:00+00:00 2026-04-27 19:50:00+00:00 LONG  663.970 664.260  0.000437    95   augx_exit_take_profit_tp3     15  True
2026-04-28 13:41:00+00:00 2026-04-28 17:45:00+00:00 LONG  658.550 656.620 -0.002931   240 augx_exit_max_hold_post_tp1     13 False
2026-04-28 18:15:00+00:00 2026-04-28 18:21:00+00:00 LONG  657.220 657.685  0.000708     5   augx_exit_take_profit_tp3     13  True
2026-04-28 19:02:00+00:00 2026-04-28 19:07:00+00:00 LONG  658.460 658.720  0.000395     5   augx_exit_take_profit_tp3     13  True
2026-04-29 13:51:00+00:00 2026-04-29 14:28:00+00:00 LONG  658.690 660.070  0.002095    37   augx_exit_take_profit_tp3     13  True
2026-04-29 18:17:00+00:00 2026-04-29 18:55:00+00:00 LONG  659.060 660.165  0.001677    38   augx_exit_take_profit_tp3     13  True
2026-04-30 14:31:00+00:00 2026-04-30 14:52:00+00:00 LONG  659.970 661.700  0.002621    21   augx_exit_take_profit_tp3     13  True
2026-04-30 18:03:00+00:00 2026-04-30 19:25:00+00:00 LONG  667.610 668.190  0.000869    82   augx_exit_take_profit_tp3     13  True
2026-05-01 13:42:00+00:00 2026-05-01 13:55:00+00:00 LONG  672.520 673.930  0.002097    13   augx_exit_take_profit_tp3     13  True
2026-05-01 15:19:00+00:00 2026-05-01 15:37:00+00:00 LONG  674.415 675.420  0.001490    18   augx_exit_take_profit_tp3     13  True
2026-05-01 19:14:00+00:00 2026-05-01 19:26:00+00:00 LONG  674.950 675.520  0.000845    12   augx_exit_take_profit_tp3     13  True
2026-05-04 13:41:00+00:00 2026-05-04 14:46:00+00:00 LONG  675.130 676.530  0.002074    65   augx_exit_take_profit_tp3     13  True
2026-05-04 18:00:00+00:00 2026-05-04 18:04:00+00:00 LONG  673.290 673.705  0.000616     4   augx_exit_take_profit_tp3     16  True
2026-05-04 19:05:00+00:00 2026-05-04 19:34:00+00:00 LONG  672.595 673.140  0.000810    26   augx_exit_take_profit_tp3     14  True
2026-05-05 13:30:00+00:00 2026-05-05 13:41:00+00:00 LONG  678.250 680.060  0.002669    11   augx_exit_take_profit_tp3     13  True
2026-05-05 15:15:00+00:00 2026-05-05 17:51:00+00:00 LONG  681.490 682.170  0.000998   149   augx_exit_take_profit_tp3     13  True
2026-05-06 13:43:00+00:00 2026-05-06 15:01:00+00:00 LONG  689.650 691.600  0.002828    78   augx_exit_take_profit_tp3     13  True
2026-05-06 18:06:00+00:00 2026-05-06 18:15:00+00:00 LONG  693.100 693.435  0.000483     9   augx_exit_take_profit_tp3     13  True
2026-05-06 19:13:00+00:00 2026-05-06 19:21:00+00:00 LONG  694.630 695.020  0.000561     8   augx_exit_take_profit_tp3     13  True
2026-05-07 13:33:00+00:00 2026-05-07 14:04:00+00:00 LONG  696.890 697.940  0.001507    31   augx_exit_take_profit_tp3     13  True
2026-05-07 14:39:00+00:00 2026-05-07 14:55:00+00:00 LONG  700.270 701.160  0.001271    16   augx_exit_take_profit_tp3     13  True
2026-05-07 18:00:00+00:00 2026-05-08 12:25:00+00:00 LONG  695.210 699.950  0.006818   121   augx_exit_take_profit_tp3     13  True
2026-05-08 13:42:00+00:00 2026-05-08 13:45:00+00:00 LONG  702.560 703.810  0.001779     3   augx_exit_take_profit_tp3     13  True
2026-05-08 14:22:00+00:00 2026-05-08 15:02:00+00:00 LONG  706.070 706.830  0.001076    40   augx_exit_take_profit_tp3     14  True
2026-05-08 19:06:00+00:00 2026-05-08 19:54:00+00:00 LONG  709.850 710.830  0.001381    48   augx_exit_take_profit_tp3     13  True
2026-05-11 14:16:00+00:00 2026-05-11 15:53:00+00:00 LONG  712.810 713.900  0.001529    97   augx_exit_take_profit_tp3     13  True
2026-05-12 13:39:00+00:00 2026-05-12 15:57:00+00:00 LONG  708.520 699.260 -0.013069   138     augx_exit_trailing_stop     16 False
2026-05-12 18:00:00+00:00 2026-05-12 18:15:00+00:00 LONG  701.180 702.015  0.001191    15   augx_exit_take_profit_tp3     14  True
2026-05-12 19:11:00+00:00 2026-05-12 19:15:00+00:00 LONG  703.400 704.335  0.001329     4   augx_exit_take_profit_tp3     13  True
2026-05-13 14:34:00+00:00 2026-05-13 15:01:00+00:00 LONG  709.700 711.155  0.002050    27   augx_exit_take_profit_tp3     13  True
2026-05-13 18:19:00+00:00 2026-05-14 13:35:00+00:00 LONG  716.150 716.850  0.000977   123   augx_exit_take_profit_tp3     13  True
2026-05-14 14:18:00+00:00 2026-05-14 14:38:00+00:00 LONG  718.100 719.260  0.001615    20   augx_exit_take_profit_tp3     13  True
2026-05-14 15:22:00+00:00 2026-05-14 16:10:00+00:00 LONG  721.220 721.920  0.000971    48   augx_exit_take_profit_tp3     13  True
2026-05-14 18:00:00+00:00 2026-05-14 19:01:00+00:00 LONG  719.980 720.550  0.000792    61   augx_exit_take_profit_tp3     13  True
2026-05-15 14:13:00+00:00 2026-05-15 14:21:00+00:00 LONG  710.320 712.170  0.002604     8   augx_exit_take_profit_tp3     13  True
2026-05-15 15:27:00+00:00 2026-05-15 17:23:00+00:00 LONG  711.400 712.800  0.001968   116   augx_exit_take_profit_tp3     13  True
2026-05-15 18:00:00+00:00 2026-05-15 18:07:00+00:00 LONG  714.375 714.960  0.000819     7   augx_exit_take_profit_tp3     14  True
2026-05-15 18:53:00+00:00 2026-05-15 20:54:00+00:00 LONG  712.730 707.550 -0.007268    77                 end_of_data     15 False
