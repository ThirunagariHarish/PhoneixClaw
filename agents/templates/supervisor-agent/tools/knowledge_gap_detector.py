"""P16: Cluster losing trades by feature signature and flag knowledge gaps.

DBSCAN over the feature vectors of losing trades; when a cluster exceeds the
threshold, we write a `specialist_proposal.json` suggesting a new specialized
agent for that regime.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


CLUSTER_MIN_SIZE = 10


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--trades", required=True,
                   help="JSON/parquet of recent trades with feature columns")
    p.add_argument("--output", required=True)
    args = p.parse_args()

    try:
        import pandas as pd
    except ImportError:
        Path(args.output).write_text(json.dumps({"error": "pandas missing"}))
        return

    trades_path = Path(args.trades)
    if not trades_path.exists():
        Path(args.output).write_text(json.dumps({"error": "no trades file"}))
        return
    if trades_path.suffix == ".parquet":
        df = pd.read_parquet(trades_path)
    else:
        df = pd.read_json(trades_path)

    if "pnl_dollar" not in df.columns and "pnl_pct" not in df.columns:
        Path(args.output).write_text(json.dumps({"error": "no pnl column"}))
        return

    pnl_col = "pnl_dollar" if "pnl_dollar" in df.columns else "pnl_pct"
    losers = df[df[pnl_col] < 0]
    if len(losers) < CLUSTER_MIN_SIZE:
        Path(args.output).write_text(json.dumps({
            "clusters": [], "note": f"only {len(losers)} losers"
        }))
        return

    # Pick feature columns defensively
    feat_cols = [c for c in ("rsi_14", "vix_level", "hour_of_day", "atr_pct",
                              "volume_ratio_20", "bb_position", "macd_histogram")
                 if c in losers.columns]
    if len(feat_cols) < 3:
        Path(args.output).write_text(json.dumps({
            "clusters": [], "note": "insufficient feature columns"
        }))
        return

    X = losers[feat_cols].fillna(0).values

    try:
        from sklearn.cluster import DBSCAN
        from sklearn.preprocessing import StandardScaler
        Xs = StandardScaler().fit_transform(X)
        labels = DBSCAN(eps=1.2, min_samples=CLUSTER_MIN_SIZE).fit_predict(Xs)
    except Exception as exc:
        Path(args.output).write_text(json.dumps({"error": str(exc)[:200]}))
        return

    clusters: list[dict] = []
    for lbl in set(labels):
        if lbl == -1:
            continue
        mask = labels == lbl
        sub = losers[mask]
        centroid = {c: round(float(sub[c].mean()), 3) for c in feat_cols}
        clusters.append({
            "cluster_id": int(lbl),
            "size": int(mask.sum()),
            "avg_loss": round(float(sub[pnl_col].mean()), 2),
            "centroid": centroid,
            "specialist_suggestion": (
                f"Consider a specialist agent for regime where "
                + ", ".join(f"{k}~{v}" for k, v in list(centroid.items())[:3])
            ),
        })

    Path(args.output).write_text(json.dumps({
        "clusters": clusters,
        "loser_count": int(len(losers)),
    }, indent=2))
    print(json.dumps({"clusters_found": len(clusters)}))


if __name__ == "__main__":
    main()
