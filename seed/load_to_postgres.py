#!/usr/bin/env python3
"""Load seed parquet files into PostgreSQL.

Usage:
    python seed/load_to_postgres.py [--db-url postgresql://seeduser:seedpass@localhost:5434/phoenix_seed]

Requires: psycopg2-binary
    pip install psycopg2-binary
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SEED_DIR = Path(__file__).parent
DEFAULT_DB_URL = "postgresql://seeduser:seedpass@localhost:5434/phoenix_seed"

TABLES = ["raw_messages", "parsed_trades", "enriched_features"]


def _check_deps() -> None:
    missing = []
    try:
        import pandas  # noqa: F401
        import pyarrow  # noqa: F401
    except ImportError:
        missing.append("pandas pyarrow")
    try:
        import sqlalchemy  # noqa: F401
    except ImportError:
        missing.append("sqlalchemy")
    try:
        import psycopg2  # noqa: F401
    except ImportError:
        missing.append("psycopg2-binary")
    if missing:
        print(f"ERROR: Missing packages. Install with:\n  pip install {' '.join(missing)}", file=sys.stderr)
        sys.exit(1)


def load(db_url: str) -> None:
    import pandas as pd
    from sqlalchemy import create_engine, text

    print(f"Connecting to {db_url} ...")
    engine = create_engine(db_url)

    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    print("Connection OK")

    for table_name in TABLES:
        parquet_path = SEED_DIR / f"{table_name}.parquet"
        if not parquet_path.exists():
            print(f"  WARNING: {parquet_path} not found — skipping")
            continue

        print(f"  Loading {table_name} ...", end="", flush=True)
        df = pd.read_parquet(parquet_path)
        df.to_sql(table_name, engine, if_exists="replace", index=False, chunksize=1000)
        print(f" {len(df):,} rows ✓")

    # Indexes for common query patterns
    index_sql = [
        "CREATE INDEX IF NOT EXISTS idx_rm_channel ON raw_messages(channel_id)",
        "CREATE INDEX IF NOT EXISTS idx_rm_author  ON raw_messages(author_name)",
        "CREATE INDEX IF NOT EXISTS idx_pt_ticker  ON parsed_trades(ticker)",
        "CREATE INDEX IF NOT EXISTS idx_pt_channel ON parsed_trades(channel_id)",
        "CREATE INDEX IF NOT EXISTS idx_pt_author  ON parsed_trades(author_name)",
        "CREATE INDEX IF NOT EXISTS idx_ef_trade   ON enriched_features(parsed_trade_id)",
        "CREATE INDEX IF NOT EXISTS idx_ef_fset    ON enriched_features(feature_set)",
    ]
    with engine.connect() as conn:
        for sql in index_sql:
            conn.execute(text(sql))
        conn.commit()

    print("Indexes created ✓")
    print(f"\nDone. Connect with:\n  psql '{db_url}'")


def main() -> None:
    _check_deps()

    parser = argparse.ArgumentParser(description="Load seed parquet files into PostgreSQL")
    parser.add_argument(
        "--db-url",
        default=DEFAULT_DB_URL,
        help=f"SQLAlchemy DB URL (default: {DEFAULT_DB_URL})",
    )
    args = parser.parse_args()
    load(args.db_url)


if __name__ == "__main__":
    main()
