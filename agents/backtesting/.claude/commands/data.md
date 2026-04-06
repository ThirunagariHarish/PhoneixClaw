Show a comprehensive data summary for the current backtesting run.

1. Read `output/transformed.parquet` if it exists:
   - Total trade count, date range (earliest to latest entry_time)
   - Win rate (is_profitable mean)
   - Unique tickers and their trade counts
   - Unique analysts and their trade counts
   - Average PnL percentage

2. Read `output/enriched.parquet` if it exists:
   - Column count (original + enriched features)
   - Any rows that were dropped during enrichment

3. Check the train/val/test split by reading numpy array shapes:
   - `output/X_train.npy`, `output/X_val.npy`, `output/X_test.npy` — row counts and feature dimensions
   - `output/y_train.npy`, `output/y_val.npy`, `output/y_test.npy` — class balance (% positive in each split)
   - `output/candle_train.npy` etc. — shape (trades x bars x features)
   - `output/text_train.npy` etc. — shape (trades x embedding_dim)

4. Show a summary table:
   ```
   Split  | Rows | Features | Candle Shape    | Text Shape    | Win Rate
   -------|------|----------|-----------------|---------------|--------
   Train  | 542  | 186      | (542, 30, 15)   | (542, 384)    | 65.3%
   Val    | 116  | 186      | (116, 30, 15)   | (116, 384)    | 64.7%
   Test   | 117  | 186      | (117, 30, 15)   | (117, 384)    | 66.1%
   ```
