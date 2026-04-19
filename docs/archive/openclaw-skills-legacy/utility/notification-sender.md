# Skill: Notification Sender

## Purpose
Send notifications to configured channels (email, Discord, Slack, push) for trade alerts, errors, or system events.

## Triggers
- When the agent needs to alert the user about a trade or event
- When user requests notification on condition (e.g., price alert)
- When execution completes, fails, or position is closed
- When system errors or critical events occur

## Inputs
- `channel`: string — "email", "discord", "slack", "push", or "all"
- `title`: string — Notification title or subject
- `body`: string — Message content (plain or markdown)
- `priority`: string — "low", "normal", "high", "critical"
- `metadata`: object — Optional: symbol, order_id, link

## Outputs
- `sent`: boolean — Whether notification was sent successfully
- `channel`: string — Channel used
- `error`: string — Error message if send failed
- `metadata`: object — Timestamp, channel config used

## Steps
1. Resolve channel config from settings (webhook URLs, API keys)
2. Validate title and body; truncate if needed for channel limits
3. Format message per channel: Discord/Slack markdown, email HTML/plain
4. For priority "critical": retry on failure; use fallback channel if configured
5. Send via channel API (Discord webhook, Slack API, SMTP, push service)
6. Log send attempt and result
7. Return sent status, channel, and any error
8. Rate-limit to avoid channel throttling

## Example
```
Input: channel="discord", title="Order Filled", body="NVDA buy 50 @ 875.20 filled", priority="normal"
Output: {
  sent: true,
  channel: "discord",
  error: null,
  metadata: {sent_at: "2025-03-03T15:05:00Z"}
}
```
