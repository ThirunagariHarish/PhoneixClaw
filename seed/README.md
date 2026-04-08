# Backtesting Seed Data

Pre-built dataset of Discord trading signals from 18 analyst channels (2-year lookback), parsed into structured trades and enriched with 200+ ML features. Use this instead of re-scraping Discord for backtesting and analysis.

| File | Size | Rows | Description |
|---|---|---|---|
| `raw_messages.parquet` | 9.2 MB | 58,314 | Raw Discord messages with full payload |
| `parsed_trades.parquet` | 1.8 MB | 11,205 | Paired entry/exit trades extracted from messages |
| `enriched_features.parquet` | 5.1 MB | 11,012 | 200+ features per trade (price action, TA, market context, etc.) |

Compressed with zstd. Total ~16 MB.

## Schema

### `raw_messages`
| Column | Type | Notes |
|---|---|---|
| `snowflake` | TEXT | Discord message ID (PK) |
| `guild_id`, `guild_name` | TEXT | Discord server |
| `channel_id`, `channel_name` | TEXT | Channel |
| `author_id`, `author_name` | TEXT | Message author |
| `content` | TEXT | Message body |
| `timestamp` | TEXT | ISO8601 UTC |
| `raw_json` | TEXT | Full Discord API payload (attachments, embeds, etc.) |
| `ingested_at` | TEXT | When fetched |

### `parsed_trades`
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER | PK |
| `channel_id`, `author_name` | TEXT | Source |
| `ticker`, `side` | TEXT | `side`='long' (no shorts in this dataset) |
| `entry_price`, `exit_price` | REAL | |
| `entry_time`, `exit_time` | TEXT | ISO8601 |
| `pnl`, `pnl_pct` | REAL | Computed P&L (handles index-level vs option premium) |
| `is_profitable` | INTEGER | 0/1 |
| `option_type`, `strike`, `expiry` | TEXT/REAL | Options metadata |
| `entry_snowflake`, `exit_snowflake` | TEXT | FK → `raw_messages.snowflake` |
| `raw_json` | TEXT | Full trade dict for debugging |

### `enriched_features`
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER | PK |
| `parsed_trade_id` | INTEGER | FK → `parsed_trades.id` |
| `feature_set` | TEXT | Version label (e.g. `v1`). Multiple sets can coexist per trade. |
| `features_json` | TEXT | Dict of ~200 features (RSI, MACD, ATR, market context, analyst stats, etc.) |
| `candle_window_json` | TEXT | Optional time-series window for DL models |
| `enriched_at` | TEXT | When computed |

Current dataset has only `feature_set='v1'`. Add new feature versions (e.g. `v2_with_gex`) without re-enriching old ones.

## Channels included (18)

**OnlyOptionsTrades — Premium:** grizzlies, zabes, tradeswithnando, luigi, eva, startedw1k, ace, anth, tostie, moe-betta, waxui

**Infra Trade Options — Premium:** other-trades-vinod, spx-es-alerts-vinod, all-trades-vinod, albert-pro-trader, sri-pro-trader, daily-trade-plan, small-account-trade

(6 Pro Alerts channels were inaccessible at ingest time and are not included.)

## Querying

### DuckDB (recommended — fastest, zero setup, real SQL on parquet)

```bash
brew install duckdb   # or: pip install duckdb
duckdb
```

```sql
CREATE VIEW raw    AS SELECT * FROM 'backtesting/seed/raw_messages.parquet';
CREATE VIEW trades AS SELECT * FROM 'backtesting/seed/parsed_trades.parquet';
CREATE VIEW feats  AS SELECT * FROM 'backtesting/seed/enriched_features.parquet';

-- Top analysts by win rate (min 50 trades)
SELECT author_name,
       COUNT(*) AS n,
       ROUND(AVG(pnl_pct), 2) AS avg_pnl_pct,
       ROUND(100.0 * SUM(is_profitable) / COUNT(*), 1) AS win_rate
FROM trades
GROUP BY 1 HAVING n >= 50
ORDER BY win_rate DESC;

-- Most-traded tickers
SELECT ticker, COUNT(*) AS n, ROUND(AVG(pnl_pct), 2) AS avg_pnl
FROM trades WHERE ticker != ''
GROUP BY 1 ORDER BY n DESC LIMIT 20;

-- Trade joined with a specific feature
SELECT t.ticker, t.pnl_pct,
       CAST(json_extract(f.features_json, '$.rsi_14') AS DOUBLE) AS rsi_14
FROM trades t
JOIN feats f ON f.parsed_trade_id = t.id
WHERE f.feature_set = 'v1'
LIMIT 20;
```

### Python — pandas

```python
import pandas as pd, json

raw    = pd.read_parquet("backtesting/seed/raw_messages.parquet")
trades = pd.read_parquet("backtesting/seed/parsed_trades.parquet")
feats  = pd.read_parquet("backtesting/seed/enriched_features.parquet")

# Explode JSON features into columns
fdf = pd.json_normalize(feats["features_json"].apply(json.loads))
full = pd.concat([feats[["parsed_trade_id", "feature_set"]], fdf], axis=1)

# Join with trade outcomes
ml_ready = trades.merge(full, left_on="id", right_on="parsed_trade_id")
print(ml_ready.shape)  # (11012, ~220)
```

### Python — DuckDB (SQL inside Python)

```python
import duckdb
con = duckdb.connect()
df = con.sql("""
    SELECT t.author_name, t.ticker, t.pnl_pct,
           json_extract(f.features_json, '$.rsi_14')::DOUBLE  AS rsi_14,
           json_extract(f.features_json, '$.atr_14')::DOUBLE  AS atr_14
    FROM 'backtesting/seed/parsed_trades.parquet' t
    JOIN 'backtesting/seed/enriched_features.parquet' f ON f.parsed_trade_id = t.id
""").df()
```

### Loading into Postgres later

```python
import pandas as pd
from sqlalchemy import create_engine

eng = create_engine("postgresql://user:pw@localhost/phoenix")
for t in ["raw_messages", "parsed_trades", "enriched_features"]:
    pd.read_parquet(f"backtesting/seed/{t}.parquet") \
      .to_sql(t, eng, if_exists="replace", index=False)
```

For analytical workloads on Postgres, convert `features_json` / `raw_json` columns to `JSONB` and add a GIN index — turns feature lookups into millisecond queries:

```sql
ALTER TABLE enriched_features
  ALTER COLUMN features_json TYPE JSONB USING features_json::jsonb;
CREATE INDEX idx_ef_features_gin ON enriched_features USING GIN (features_json);
```

## Regenerating

To rebuild from scratch (re-scrape Discord → re-parse → re-enrich):

```bash
python3 backtesting/scratch/ingest_parallel.py    # raw_messages
python3 backtesting/scratch/transform.py          # parsed_trades
python3 backtesting/scratch/enrich_db.py          # enriched_features
python3 -c "
import sqlite3, pandas as pd
c = sqlite3.connect('db/phoenix.db')
for t in ['raw_messages','parsed_trades','enriched_features']:
    pd.read_sql(f'SELECT * FROM {t}', c) \
      .to_parquet(f'backtesting/seed/{t}.parquet', compression='zstd', index=False)
"
```

Requires `DISCORD_TOKEN` in `.env`. Ingest is parallel (8 workers, ~5 min), transform is instant, enrich is the slow step (~25 min, market data fetches via yfinance).
