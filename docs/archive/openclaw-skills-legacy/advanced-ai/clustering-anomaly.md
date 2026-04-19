# Clustering Anomaly

## Purpose
Detect anomalies using clustering (e.g., isolation forest, DBSCAN) for outlier detection.

## Category
advanced-ai

## Triggers
- When detecting unusual price/volume behavior
- When screening for potential manipulation
- When validating data quality
- When flagging regime shifts

## Inputs
- `data`: object — Feature matrix or time series
- `method`: string — "isolation_forest", "dbscan", "lof", "zscore"
- `contamination`: number — Expected anomaly fraction (default: 0.01)
- `features`: string[] — Features to use (optional)
- `threshold`: number — Anomaly score threshold (optional)

## Outputs
- `anomalies`: object[] — Detected anomaly indices or timestamps
- `scores`: number[] — Anomaly scores per observation
- `labels`: number[] — Cluster or anomaly labels (-1 = anomaly)
- `metadata`: object — Method, contamination, n_anomalies

## Steps
1. Prepare feature matrix from data
2. Fit anomaly detector (isolation forest, DBSCAN, etc.)
3. Compute scores and labels
4. Filter by threshold or top-k
5. Return anomalies, scores, labels
6. Optionally persist for monitoring

## Example
```
Input: data={returns: [...], volume: [...]}, method="isolation_forest", contamination=0.02
Output: {
  anomalies: [{index: 45, timestamp: "2025-02-15T10:30:00", score: 0.92}],
  scores: [0.1, 0.2, ..., 0.92],
  labels: [0, 0, ..., -1],
  metadata: {method: "isolation_forest", n_anomalies: 5}
}
```

## Notes
- Isolation forest works well for high-dimensional data
- DBSCAN requires tuning eps and min_samples
- Use for pre-trade validation or post-trade review
