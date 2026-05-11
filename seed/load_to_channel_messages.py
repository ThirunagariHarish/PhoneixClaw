#!/usr/bin/env python3
"""One-shot seed loader: parquet -> channel_messages.

Reads /tmp/raw_messages.parquet (already on api pod) and bulk-inserts into
the channel_messages table using a single fixed connector_id. Maps fields,
generates UUIDs for the primary key, and packs raw_json into raw_data jsonb.
Idempotent: skips rows whose platform_message_id already exists.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from datetime import datetime

import asyncpg
import pyarrow.parquet as pq

PARQUET_PATH = "/tmp/raw_messages.parquet"
CONNECTOR_ID = "75e33f2a-ee6d-4d3b-a570-b060343f0d1f"
AGENT_ID = "e9dc18c1-329a-42b2-b90d-af81d8288192"

DB_URL = os.environ.get("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")
if not DB_URL:
    raise SystemExit("DATABASE_URL not set")

# Strip Discord emoji + separator prefixes ("📈┃other-trades-vinod" -> "other-trades-vinod")
CHANNEL_PREFIX_RE = re.compile(r"^[^\w]+")


def _strip_channel_prefix(name: str) -> str:
    return CHANNEL_PREFIX_RE.sub("", name or "").strip() or name


# Tickers heuristic: $XYZ or standalone all-caps 1-5 letters in content. Keep cheap.
TICKER_RE = re.compile(r"\$([A-Z]{1,5})\b|\b([A-Z]{2,5})\b")


def _extract_tickers(content: str) -> list[str]:
    if not content:
        return []
    found = set()
    for m in TICKER_RE.finditer(content):
        sym = m.group(1) or m.group(2)
        if sym and 2 <= len(sym) <= 5 and sym not in {"THE", "AND", "FOR", "ARE", "BUT", "NOT", "YOU", "ALL", "CAN", "HAD", "HER", "WAS", "ONE", "OUR", "OUT", "DAY", "GET", "HAS", "HIM", "HIS", "HOW", "MAN", "NEW", "NOW", "OLD", "SEE", "TWO", "WAY", "WHO", "BOY", "DID", "ITS", "LET", "PUT", "SAY", "SHE", "TOO", "USE"}:
            found.add(sym)
    return sorted(found)[:10]


async def main() -> None:
    print(f"Reading {PARQUET_PATH} ...", flush=True)
    table = pq.read_table(PARQUET_PATH)
    df = table.to_pandas()
    print(f"  {len(df):,} rows", flush=True)

    conn = await asyncpg.connect(DB_URL)
    try:
        # Pre-fetch existing platform_message_ids for this connector to skip dupes.
        existing = {
            r["platform_message_id"]
            for r in await conn.fetch(
                "SELECT platform_message_id FROM channel_messages WHERE connector_id = $1",
                uuid.UUID(CONNECTOR_ID),
            )
        }
        print(f"  {len(existing):,} existing rows for this connector — will skip dupes", flush=True)

        records = []
        skipped = 0
        for _, row in df.iterrows():
            pmid = str(row["snowflake"])
            if pmid in existing:
                skipped += 1
                continue
            content = row["content"] or ""
            ts = row["timestamp"]
            if isinstance(ts, str):
                posted_at = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            else:
                posted_at = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
            channel_clean = _strip_channel_prefix(row["channel_name"])
            try:
                raw_data = json.loads(row["raw_json"]) if row["raw_json"] else {}
            except Exception:
                raw_data = {"_raw_string": str(row["raw_json"])[:500]}
            records.append(
                (
                    uuid.uuid4(),                                      # id
                    uuid.UUID(CONNECTOR_ID),                           # connector_id
                    channel_clean[:200],                               # channel
                    str(row["channel_id"])[:20],                       # channel_id_snowflake
                    None,                                              # backfill_run_id
                    str(row["author_name"])[:200],                     # author
                    content,                                           # content
                    "text",                                            # message_type
                    json.dumps(_extract_tickers(content)),             # tickers_mentioned
                    json.dumps(raw_data, default=str),                 # raw_data
                    pmid[:100],                                        # platform_message_id
                    posted_at,                                         # posted_at
                    datetime.now(),                                    # created_at
                )
            )
        print(f"  prepared {len(records):,} new records (skipped {skipped:,} dupes)", flush=True)

        if not records:
            print("Nothing to insert.")
            return

        await conn.copy_records_to_table(
            "channel_messages",
            records=records,
            columns=[
                "id", "connector_id", "channel", "channel_id_snowflake",
                "backfill_run_id", "author", "content", "message_type",
                "tickers_mentioned", "raw_data", "platform_message_id", "posted_at",
                "created_at",
            ],
        )
        print(f"Inserted {len(records):,} rows.")

        # Link agent → connector if not already linked.
        link = await conn.fetchrow(
            "SELECT 1 FROM connector_agents WHERE agent_id = $1 AND connector_id = $2",
            uuid.UUID(AGENT_ID), uuid.UUID(CONNECTOR_ID),
        )
        if link:
            print("connector_agents link already exists.")
        else:
            await conn.execute(
                """
                INSERT INTO connector_agents (id, connector_id, agent_id, channel, is_active, created_at)
                VALUES ($1, $2, $3, $4, true, now())
                """,
                uuid.uuid4(), uuid.UUID(CONNECTOR_ID), uuid.UUID(AGENT_ID), "other-trades-vinod",
            )
            print(f"Linked agent {AGENT_ID} <-> connector {CONNECTOR_ID}.")

        # Sanity print
        n = await conn.fetchval("SELECT count(*) FROM channel_messages WHERE connector_id = $1", uuid.UUID(CONNECTOR_ID))
        n_other = await conn.fetchval("SELECT count(*) FROM channel_messages WHERE connector_id = $1 AND channel = 'other-trades-vinod'", uuid.UUID(CONNECTOR_ID))
        print(f"channel_messages connector total: {n:,} | 'other-trades-vinod' channel: {n_other:,}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
