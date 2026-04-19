# Discord Channel Reader

## Purpose
Read Discord channel history for behavior extraction, sentiment analysis, or trade idea aggregation.

## Category
utility

## Triggers
- When user requests Discord channel content
- When building behavior profile from trader Discord activity
- When aggregating trade ideas or sentiment from community channels
- When syncing Discord messages for analysis pipeline

## Inputs
- `channel_id`: string — Discord channel ID
- `limit`: number — Max messages to fetch (default: 100, max: 100)
- `before`: string — Message ID to fetch before (for pagination)
- `after`: string — Message ID to fetch after (for pagination)
- `include_embeds`: boolean — Include embed content (default: true)
- `include_reactions`: boolean — Include reaction counts (default: false)
- `filter_author`: string — Optional: only messages from user ID
- `bot_token`: string — Discord bot token (or from env)

## Outputs
- `messages`: object[] — [{id, author, content, timestamp, attachments}]
- `has_more`: boolean — More messages available (paginate with before/after)
- `channel_name`: string — Channel name
- `guild_name`: string — Guild/server name
- `metadata`: object — channel_id, count, fetched_at

## Steps
1. Validate bot_token; ensure bot has read access to channel
2. Call Discord API: GET /channels/{channel_id}/messages with limit, before, after
3. Parse each message: id, author (username, id), content, timestamp
4. If include_embeds: extract embed title, description, url
5. If include_reactions: fetch reaction counts per message
6. If filter_author: filter to matching author id
7. Fetch channel and guild names from channel/guild endpoints
8. Return messages, has_more, channel_name, guild_name, metadata
9. Respect rate limits (5 req/sec per endpoint); use exponential backoff
10. Log fetch for audit; support pagination for large histories

## Example
```
Input: channel_id="123456789", limit=50, include_embeds=true
Output: {
  messages: [
    {id: "msg1", author: "TraderJoe", content: "Long NVDA 900c for earnings", timestamp: "2025-03-03T14:00:00Z", attachments: []},
    ...
  ],
  has_more: true,
  channel_name: "trading-ideas",
  guild_name: "Trading Community",
  metadata: {channel_id: "123456789", count: 50, fetched_at: "2025-03-03T15:00:00Z"}
}
```

## Notes
- Requires Discord bot with MESSAGE_CONTENT intent for full content
- Some channels restrict bot access; handle 403 gracefully
- Consider discord-message-reader skill for consistency with existing data skills
