Analyze the feature set used in this backtesting run.

1. Read `output/enriched.parquet` using Python:
   ```python
   import pandas as pd
   df = pd.read_parquet("output/enriched.parquet")
   ```

2. Show:
   - Total columns count and total rows
   - List ALL column names grouped by category:
     - Original trade columns (ticker, entry_time, exit_time, pnl_pct, etc.)
     - Price Action features (return_*, gap_*, range_*, atr_*, fib_*, candle_*)
     - Technical Indicators (rsi_*, macd_*, bollinger_*, stoch_*, adx_*, cci_*, etc.)
     - Moving Averages (sma_*, ema_*, distance_*, crossover_*)
     - Volume features (volume_*, vwap_*, obv_*, ad_*)
     - Market Context (spy_*, qqq_*, vix_*, sector_*, corr_*)
     - Time features (hour_*, day_*, month_*, is_*, opex_*)
     - Sentiment (sentiment_*, analyst_*)
     - Options (options_*, gex_*, iv_*, avg_delta/gamma/theta/vega)
     - Temporal cross-trade features (ticker_rolling_*, streak_*, momentum_*, regime_*)

3. For each column, show the percentage of NaN values. Flag any column with >50% NaN.

4. Show the tabular feature count from preprocessing:
   - Read `output/X_train.npy` shape to get the actual feature count used in training
   - Compare with total enriched columns to show how many were filtered out

5. If `output/candle_windows.npy` exists, show its shape (trades x bars x features).
