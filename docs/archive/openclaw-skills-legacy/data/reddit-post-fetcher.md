# Skill: Reddit Post Fetcher

## Purpose
Fetch posts from Reddit subreddits to gather trading discussions, stock mentions, and market sentiment for analysis and signal generation.

## Triggers
- When the agent needs Reddit data for sentiment analysis
- When user requests subreddit monitoring (e.g., r/wallstreetbets, r/stocks)
- When building social sentiment pipelines
- When backtesting requires historical Reddit post data

## Inputs
- `subreddits`: string[] — Subreddit names (e.g., ["wallstreetbets", "stocks"])
- `sort`: string — Sort order: "hot", "new", "top", "rising" (default: "hot")
- `time_filter`: string — For "top": "hour", "day", "week", "month", "year"
- `limit`: number — Max posts per subreddit (default: 25, max 100)
- `include_comments`: boolean — Whether to fetch top-level comments (default: false)

## Outputs
- `posts`: object[] — Post objects with id, title, selftext, score, num_comments, created_utc, subreddit
- `ticker_mentions`: object[] — Extracted tickers with post/comment counts
- `metadata`: object — Fetch timestamp, subreddits_queried, total_posts

## Steps
1. Initialize Reddit API client (PRAW or direct REST) with client_id, client_secret, user_agent
2. Validate subreddit names exist and are accessible (handle private/banned)
3. For each subreddit, fetch posts using appropriate endpoint (e.g., /r/{sub}/hot.json)
4. Apply sort and time_filter parameters; respect rate limit (60 requests/min for OAuth)
5. Parse each post: extract id, title, selftext, score, upvote_ratio, num_comments, created_utc
6. If include_comments=true, fetch top N comments per post (limit to avoid rate limits)
7. Run ticker extraction on title + selftext + comments using $TICKER or symbol regex
8. Aggregate ticker mentions across all posts; weight by score if desired
9. Deduplicate posts by id; sort by created_utc or score
10. Return posts array with metadata

## Example
```
Input: subreddits=["wallstreetbets", "stocks"], sort="hot", limit=50
Output: {
  posts: [{id: "abc123", title: "NVDA to the moon?", selftext: "...", score: 4521, subreddit: "wallstreetbets"}],
  ticker_mentions: [{symbol: "NVDA", count: 34, total_score: 12500}, {symbol: "TSLA", count: 22}],
  metadata: {fetched_at: "2025-03-03T15:00:00Z", subreddits: 2, total_posts: 100}
}
```
