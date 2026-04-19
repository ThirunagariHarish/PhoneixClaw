# Skill: Discord Message Reader

## Purpose
Read and parse messages from Discord channels to extract trading-related signals, ticker mentions, and community sentiment for the OpenClaw trading system.

## Triggers
- When the agent needs to monitor Discord channels for trading signals
- When user requests Discord data ingestion or message parsing
- When setting up social sentiment pipelines that include Discord
- When backtesting requires historical Discord message data

## Inputs
- `channel_ids`: string[] — Comma-separated Discord channel IDs to monitor
- `guild_id`: string — Discord server (guild) ID
- `lookback_hours`: number — Hours of messages to fetch (default: 24)
- `message_limit`: number — Max messages per channel (default: 100)
- `filters`: object — Optional filters: keywords, ticker_pattern, exclude_bots

## Outputs
- `messages`: object[] — Parsed messages with timestamp, author, content, channel_id
- `ticker_mentions`: object[] — Extracted ticker symbols with mention count
- `metadata`: object — Fetch timestamp, message_count, channels_scanned

## Steps
1. Authenticate with Discord API using configured bot token or OAuth credentials
2. Resolve channel IDs and validate read permissions for each channel
3. Fetch messages from each channel using Discord REST API (messages endpoint)
4. Apply pagination for channels exceeding message_limit; respect rate limits (50 req/s)
5. Parse each message: extract timestamp (ISO 8601), author_id, content, attachments
6. Run ticker extraction: match $TICKER, TICKER, or configured regex patterns
7. Apply optional filters: keyword whitelist/blacklist, exclude bot messages
8. Deduplicate and sort messages by timestamp descending
9. Aggregate ticker mentions per symbol across all channels
10. Return structured output with messages array and metadata

## Example
```
Input: channel_ids=["123456789", "987654321"], lookback_hours=6, filters={keywords: ["earnings", "catalyst"]}
Output: {
  messages: [{id: "msg1", content: "NVDA earnings beat - looking bullish", tickers: ["NVDA"], timestamp: "2025-03-03T14:30:00Z"}],
  ticker_mentions: [{symbol: "NVDA", count: 12}, {symbol: "AAPL", count: 5}],
  metadata: {fetched_at: "2025-03-03T15:00:00Z", total_messages: 847}
}
```
