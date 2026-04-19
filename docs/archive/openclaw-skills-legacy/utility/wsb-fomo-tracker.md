# WSB FOMO Tracker

## Purpose
Scan Reddit/WallStreetBets for retail FOMO or YOLO spikes to gauge crowd sentiment extremes.

## Category
utility

## Triggers
- When user requests WSB FOMO/YOLO metrics for a symbol
- When assessing retail euphoria or panic
- When building contrarian or momentum signals from crowd behavior
- When screening for meme stock activity

## Inputs
- `symbol`: string — Ticker (e.g., GME, AMC, NVDA)
- `subreddit`: string — Subreddit (default: "wallstreetbets")
- `lookback_hours`: number — Hours to scan (default: 24)
- `metrics`: string[] — ["fomo_score", "yolo_count", "mention_volume", "sentiment"]
- `reddit_credentials`: object — client_id, client_secret, or from env

## Outputs
- `fomo_score`: number — 0–100, retail euphoria level
- `yolo_count`: number — Posts/comments with YOLO/calls/all-in language
- `mention_volume`: number — Total mentions of symbol
- `sentiment`: string — "euphoric", "bullish", "neutral", "bearish", "panic"
- `top_posts`: object[] — [{title, score, url, sentiment}]
- `metadata`: object — symbol, subreddit, lookback, computed_at

## Steps
1. Fetch Reddit posts/comments for subreddit; filter by symbol mention
2. Parse for FOMO keywords: "YOLO", "moon", "diamond hands", "to the moon", "calls printing"
3. Parse for panic keywords: "rug pull", "bag holder", "sell"
4. fomo_score: weighted combo of YOLO density, call mentions, upvote velocity
5. yolo_count: count of YOLO/all-in language
6. sentiment: map fomo_score and keyword mix to sentiment label
7. Return fomo_score, yolo_count, mention_volume, sentiment, top_posts, metadata
8. Respect Reddit rate limits; cache with 30m TTL

## Example
```
Input: symbol="GME", lookback_hours=24
Output: {
  fomo_score: 72,
  yolo_count: 45,
  mention_volume: 1200,
  sentiment: "euphoric",
  top_posts: [{title: "GME calls printing", score: 5000, url: "...", sentiment: "bullish"}],
  metadata: {symbol: "GME", subreddit: "wallstreetbets", lookback: 24, computed_at: "2025-03-03T15:00:00Z"}
}
```

## Notes
- Reddit API or PRAW; consider reddit-post-fetcher if exists
- Extreme FOMO can be contrarian signal; combine with twitter-sentiment-velocity
- Meme stocks: GME, AMC, BBBY historically; expand to any symbol
