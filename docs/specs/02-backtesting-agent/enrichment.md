# Spec: Market Enrichment Pipeline (Backtesting Step 2)

## Purpose

Add ~200 market attributes to each trade row from the transformation step. All data must be **point-in-time** — only use data available at or before the trade entry timestamp to prevent look-ahead bias.

## Input

Parquet from Step 1 with columns: `trade_id`, `ticker`, `entry_time`, `entry_price`, `side`, etc.

## Output

Same DataFrame with ~200 additional columns across 8 categories.

## Category 1: Price Action (~30 attributes)

| # | Attribute | Calculation | Source |
|---|-----------|-------------|--------|
| 1 | `close_1d` | Close price 1 day before entry | yfinance |
| 2 | `close_3d` | Close price 3 days before entry | yfinance |
| 3 | `close_5d` | Close price 5 days before entry | yfinance |
| 4 | `close_10d` | Close price 10 days before entry | yfinance |
| 5 | `close_20d` | Close price 20 days before entry | yfinance |
| 6 | `return_1d` | 1-day return: (close_0 - close_1) / close_1 | Derived |
| 7 | `return_3d` | 3-day return | Derived |
| 8 | `return_5d` | 5-day return | Derived |
| 9 | `return_10d` | 10-day return | Derived |
| 10 | `return_20d` | 20-day return | Derived |
| 11 | `gap_pct` | Overnight gap: (open - prev_close) / prev_close | Derived |
| 12 | `range_pct` | Daily range: (high - low) / close | Derived |
| 13 | `body_pct` | Candle body: abs(close - open) / close | Derived |
| 14 | `upper_shadow` | (high - max(open,close)) / close | Derived |
| 15 | `lower_shadow` | (min(open,close) - low) / close | Derived |
| 16 | `is_doji` | body_pct < 0.1 * range_pct | Derived |
| 17 | `is_hammer` | lower_shadow > 2 * body_pct, small upper shadow | Derived |
| 18 | `is_engulfing_bull` | Current body engulfs previous, close > open | Derived |
| 19 | `is_engulfing_bear` | Current body engulfs previous, close < open | Derived |
| 20 | `is_morning_star` | 3-candle reversal pattern | Derived |
| 21 | `atr_14` | Average True Range (14 periods) | ta-lib |
| 22 | `atr_pct` | ATR / close (normalized) | Derived |
| 23 | `true_range` | max(high-low, abs(high-prev_close), abs(low-prev_close)) | Derived |
| 24 | `high_5d` | 5-day high | yfinance |
| 25 | `low_5d` | 5-day low | yfinance |
| 26 | `high_20d` | 20-day high | yfinance |
| 27 | `low_20d` | 20-day low | yfinance |
| 28 | `dist_from_52w_high` | (price - 52w_high) / 52w_high | Derived |
| 29 | `dist_from_52w_low` | (price - 52w_low) / 52w_low | Derived |
| 30 | `consecutive_green` | Count of consecutive green candles before entry | Derived |

## Category 2: Technical Indicators (~40 attributes)

| # | Attribute | Period(s) | Source |
|---|-----------|-----------|--------|
| 31 | `rsi_14` | 14 | ta |
| 32 | `rsi_7` | 7 | ta |
| 33 | `rsi_21` | 21 | ta |
| 34 | `macd_line` | 12, 26 | ta |
| 35 | `macd_signal` | 9 | ta |
| 36 | `macd_histogram` | — | ta |
| 37 | `macd_cross_up` | MACD crosses above signal | Derived |
| 38 | `bb_upper` | 20, 2 std | ta |
| 39 | `bb_middle` | 20 SMA | ta |
| 40 | `bb_lower` | 20, 2 std | ta |
| 41 | `bb_position` | (price - lower) / (upper - lower) | Derived |
| 42 | `bb_width` | (upper - lower) / middle | Derived |
| 43 | `stoch_k` | 14, 3 | ta |
| 44 | `stoch_d` | 3 | ta |
| 45 | `adx_14` | 14 | ta |
| 46 | `di_plus` | +DI 14 | ta |
| 47 | `di_minus` | -DI 14 | ta |
| 48 | `cci_20` | 20 | ta |
| 49 | `williams_r` | 14 | ta |
| 50 | `obv` | — | ta |
| 51 | `obv_slope_5` | OBV 5-day slope | Derived |
| 52 | `mfi_14` | 14 | ta |
| 53 | `ichimoku_tenkan` | 9 | ta |
| 54 | `ichimoku_kijun` | 26 | ta |
| 55 | `ichimoku_cloud_top` | — | ta |
| 56 | `ichimoku_cloud_bottom` | — | ta |
| 57 | `above_cloud` | price > cloud_top | Derived |
| 58 | `vwap` | intraday or daily approx | ta |
| 59 | `pivot_point` | (H + L + C) / 3 | Derived |
| 60 | `pivot_r1` | 2*PP - L | Derived |
| 61 | `pivot_s1` | 2*PP - H | Derived |
| 62 | `fib_236` | 23.6% retrace of 20d range | Derived |
| 63 | `fib_382` | 38.2% retrace | Derived |
| 64 | `fib_618` | 61.8% retrace | Derived |
| 65 | `keltner_upper` | EMA20 + 2*ATR | Derived |
| 66 | `keltner_lower` | EMA20 - 2*ATR | Derived |
| 67 | `parabolic_sar` | — | ta |
| 68 | `sar_trend` | price > SAR = bullish | Derived |
| 69 | `roc_10` | Rate of change 10 | ta |
| 70 | `tsi` | True Strength Index | ta |

## Category 3: Moving Averages (~20 attributes)

| # | Attribute | Source |
|---|-----------|--------|
| 71-76 | `sma_5`, `sma_10`, `sma_20`, `sma_50`, `sma_100`, `sma_200` | ta |
| 77-82 | `ema_5`, `ema_10`, `ema_20`, `ema_50`, `ema_100`, `ema_200` | ta |
| 83 | `dist_sma_20` | (price - SMA20) / SMA20 | Derived |
| 84 | `dist_sma_50` | (price - SMA50) / SMA50 | Derived |
| 85 | `dist_sma_200` | (price - SMA200) / SMA200 | Derived |
| 86 | `sma_20_50_cross` | SMA20 > SMA50 (golden cross flag) | Derived |
| 87 | `sma_50_200_cross` | SMA50 > SMA200 | Derived |
| 88 | `sma_20_slope` | 5-day slope of SMA20 | Derived |
| 89 | `sma_50_slope` | 5-day slope of SMA50 | Derived |
| 90 | `above_all_sma` | price > SMA20 and SMA50 and SMA200 | Derived |

## Category 4: Volume (~15 attributes)

| # | Attribute | Source |
|---|-----------|--------|
| 91 | `volume` | Raw volume | yfinance |
| 92 | `volume_sma_20` | 20-day average volume | Derived |
| 93 | `volume_ratio` | volume / volume_sma_20 | Derived |
| 94 | `volume_ratio_5d` | 5-day avg volume / 20-day avg | Derived |
| 95 | `ad_line` | Accumulation/Distribution | ta |
| 96 | `chaikin_mf` | Chaikin Money Flow 20 | ta |
| 97 | `force_index` | Close change * volume | Derived |
| 98 | `volume_price_trend` | Cum sum of volume * price change | ta |
| 99 | `ease_of_movement` | (H+L)/2 change / (volume/1e6) | ta |
| 100 | `negative_volume_index` | — | ta |
| 101 | `volume_weighted_ma` | VWMA 20 | Derived |
| 102 | `on_balance_volume_ema` | EMA of OBV | Derived |
| 103 | `volume_breakout` | volume > 2 * volume_sma_20 | Derived |
| 104 | `relative_volume` | volume / same-time-of-day avg | Derived |
| 105 | `volume_trend_5d` | Slope of volume over 5 days | Derived |

## Category 5: Market Context (~25 attributes)

| # | Attribute | Source |
|---|-----------|--------|
| 106 | `spy_return_1d` | SPY 1-day return | yfinance |
| 107 | `spy_return_5d` | SPY 5-day return | yfinance |
| 108 | `qqq_return_1d` | QQQ 1-day return | yfinance |
| 109 | `iwm_return_1d` | IWM 1-day return | yfinance |
| 110 | `vix_level` | VIX close | yfinance |
| 111 | `vix_change_1d` | VIX 1-day change | Derived |
| 112 | `vix_percentile_30d` | VIX percentile over 30 days | Derived |
| 113 | `vix_term_structure` | VIX - VIX3M (contango/backwardation) | yfinance |
| 114 | `put_call_ratio` | CBOE equity put/call | Finnhub / CBOE |
| 115 | `advance_decline` | NYSE advancers / decliners | yfinance |
| 116 | `sector_xlk_1d` | XLK (tech) 1-day return | yfinance |
| 117 | `sector_xlf_1d` | XLF (financials) 1-day return | yfinance |
| 118 | `sector_xle_1d` | XLE (energy) 1-day return | yfinance |
| 119 | `sector_xlv_1d` | XLV (healthcare) 1-day return | yfinance |
| 120 | `sector_xlu_1d` | XLU (utilities) 1-day return | yfinance |
| 121 | `corr_spy_20d` | 20-day correlation with SPY | Derived |
| 122 | `beta_spy_60d` | 60-day beta to SPY | Derived |
| 123 | `relative_strength_20d` | Ticker return / SPY return over 20d | Derived |
| 124 | `breadth_50d_pct` | % of S&P above 50-day MA | External |
| 125 | `dxy_level` | Dollar index | yfinance (DX-Y.NYB) |
| 126 | `tnx_level` | 10-year treasury yield | yfinance (^TNX) |
| 127 | `gold_return_1d` | GLD 1-day return | yfinance |
| 128 | `oil_return_1d` | USO 1-day return | yfinance |
| 129 | `btc_return_1d` | BTC-USD 1-day return | yfinance |
| 130 | `market_regime` | Bull/bear/sideways (SMA200 slope) | Derived |

## Category 6: Time Features (~15 attributes)

| # | Attribute | Source |
|---|-----------|--------|
| 131 | `hour_of_day` | 0-23 | entry_time |
| 132 | `minute_of_hour` | 0-59 | entry_time |
| 133 | `day_of_week` | 0=Mon, 4=Fri | entry_time |
| 134 | `day_of_month` | 1-31 | entry_time |
| 135 | `month` | 1-12 | entry_time |
| 136 | `quarter` | 1-4 | entry_time |
| 137 | `is_pre_market` | entry_time < 9:30 ET | Derived |
| 138 | `is_post_market` | entry_time > 16:00 ET | Derived |
| 139 | `is_first_hour` | 9:30-10:30 ET | Derived |
| 140 | `is_last_hour` | 15:00-16:00 ET | Derived |
| 141 | `is_opex_week` | 3rd Friday of month week | Derived |
| 142 | `days_to_opex` | Days until next monthly opex | Derived |
| 143 | `days_since_last_trade` | Days since this analyst's last trade | Derived |
| 144 | `is_monday` | Boolean | Derived |
| 145 | `is_friday` | Boolean | Derived |

## Category 7: Sentiment + Events (~30 attributes)

| # | Attribute | Source |
|---|-----------|--------|
| 146 | `hourly_sentiment` | News sentiment for ticker at entry hour | Finnhub / News API |
| 147 | `daily_sentiment` | Average daily sentiment | Finnhub |
| 148 | `sentiment_3d_avg` | 3-day rolling sentiment | Derived |
| 149 | `sentiment_momentum` | sentiment_today - sentiment_3d_avg | Derived |
| 150 | `days_to_earnings` | Days until next earnings report | Finnhub |
| 151 | `days_after_earnings` | Days since last earnings | Finnhub |
| 152 | `earnings_surprise_last` | Last earnings surprise % | Finnhub |
| 153 | `is_earnings_week` | Earnings within 5 trading days | Derived |
| 154 | `days_to_fed` | Days until next FOMC meeting | FRED / hardcoded calendar |
| 155 | `is_fed_week` | FOMC within 5 days | Derived |
| 156 | `days_to_cpi` | Days until next CPI release | FRED |
| 157 | `days_to_jobs` | Days until next NFP release | FRED |
| 158 | `econ_events_today` | Count of major economic events today | Finnhub |
| 159 | `analyst_rating` | Consensus rating (1-5 scale) | Finnhub |
| 160 | `analyst_target_vs_price` | (analyst_target - price) / price | Finnhub |
| 161 | `short_interest_pct` | Short interest as % of float | Finnhub |
| 162 | `insider_buy_90d` | Count of insider buys in 90 days | Finnhub |
| 163 | `insider_sell_90d` | Count of insider sells in 90 days | Finnhub |
| 164 | `institutional_ownership_change` | QoQ change in institutional ownership | Derived |
| 165 | `news_volume_1d` | Number of news articles in last 24h | Finnhub |
| 166 | `news_volume_7d` | Number of news articles in last 7 days | Finnhub |
| 167 | `social_mention_count` | Social media mentions (if available) | External |
| 168 | `unusual_options_flag` | Unusual options activity detected | Unusual Whales |
| 169 | `unusual_call_volume` | Call volume > 2x average | Unusual Whales |
| 170 | `unusual_put_volume` | Put volume > 2x average | Unusual Whales |
| 171 | `smart_money_flow` | Institutional options flow indicator | Unusual Whales |
| 172 | `congressional_trade` | Congressional member traded this ticker | External |
| 173 | `sector_news_sentiment` | Sector-level news sentiment | Derived |
| 174 | `geopolitical_risk_index` | GPR index level (if available from FRED) | FRED |
| 175 | `fear_greed_index` | CNN Fear & Greed or proxy (VIX + put/call) | Derived |

## Category 8: Options-Specific (~25 attributes)

| # | Attribute | Source |
|---|-----------|--------|
| 176 | `iv_rank_30d` | IV rank over 30 days | Unusual Whales / derived |
| 177 | `iv_percentile_252d` | IV percentile over 1 year | Derived |
| 178 | `iv_current` | Current implied volatility | Unusual Whales |
| 179 | `hv_20` | 20-day historical volatility | Derived |
| 180 | `iv_hv_spread` | IV - HV (volatility premium) | Derived |
| 181 | `option_delta` | Delta of the traded option | Derived / UW |
| 182 | `option_gamma` | Gamma | Derived / UW |
| 183 | `option_theta` | Theta (daily decay) | Derived / UW |
| 184 | `option_vega` | Vega | Derived / UW |
| 185 | `days_to_expiry` | Calendar days to option expiry | Derived |
| 186 | `max_pain` | Max pain price for expiry | Unusual Whales |
| 187 | `dist_from_max_pain` | (price - max_pain) / max_pain | Derived |
| 188 | `total_open_interest` | Total OI at strike | Unusual Whales |
| 189 | `put_call_oi_ratio` | Put OI / Call OI at strike | Derived |
| 190 | `net_gamma_exposure` | Market-maker gamma exposure | Derived |
| 191 | `iv_skew_25d` | 25-delta put IV - 25-delta call IV | Derived |
| 192 | `term_structure_slope` | Front-month IV vs back-month IV | Derived |
| 193 | `option_volume_ratio` | Option volume / avg option volume | Derived |
| 194 | `itm_probability` | Probability of being in-the-money | Derived (Black-Scholes) |
| 195 | `breakeven_price` | Entry + premium for options | Derived |
| 196 | `risk_reward_ratio` | Potential gain / potential loss | Derived |
| 197 | `is_weekly_option` | Expiry within 7 days | Derived |
| 198 | `is_0dte` | Expiry today | Derived |
| 199 | `underlying_vs_strike` | (underlying - strike) / strike | Derived |
| 200 | `gex_level` | Gamma Exposure at current price level | Derived |

## Candle Duration for Indicators

For each trade, indicators are calculated using **daily candles** with a **60-day lookback** window ending at the trading day before entry (to avoid look-ahead bias). For intraday timing features, use the 5-minute chart of the entry day up to entry time.

## API Rate Limit Strategy

| API | Free Tier Limit | Strategy |
|-----|----------------|----------|
| yfinance | No formal limit | Batch by ticker, cache locally, sleep 0.5s between requests |
| Finnhub | 60 calls/min (free) | Queue + rate limiter, cache 24h |
| FRED | 120 calls/min | Batch by series, cache weekly |
| Unusual Whales | Per subscription | Cache daily, batch requests |
| Alpha Vantage | 5 calls/min (free) | Fallback only; prefer yfinance |

## Tool Script

```
agents/backtesting/tools/enrich.py
```

CLI:
```bash
python tools/enrich.py \
    --input output/transformed.parquet \
    --output output/enriched.parquet \
    --uw-api-key $UNUSUAL_WHALES_KEY \
    --finnhub-key $FINNHUB_KEY
```

## Files to Create

| File | Action |
|------|--------|
| `agents/backtesting/tools/enrich.py` | New — main enrichment script |
| `agents/backtesting/tools/indicators.py` | New — technical indicator calculations |
| `agents/backtesting/tools/market_context.py` | New — SPY/VIX/sector data |
| `agents/backtesting/tools/sentiment_events.py` | New — Finnhub/FRED/news integration |
| `agents/backtesting/tools/options_data.py` | New — IV, Greeks, Unusual Whales |
