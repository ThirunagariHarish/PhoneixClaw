# Alert Composer

## Purpose
Compose and format alerts for various channels (email, Slack, SMS, webhook) with consistent structure.

## Category
utility

## Triggers
- When a trade signal or execution event occurs
- When risk threshold is breached
- When user configures alert rules
- When system events require notification

## Inputs
- `channel`: string — "email", "slack", "sms", "webhook", or "all"
- `alert_type`: string — "trade", "risk", "system", "price", "custom"
- `title`: string — Short alert title
- `body`: string — Alert message body
- `priority`: string — "low", "medium", "high", "critical"
- `metadata`: object — Optional key-value pairs for routing
- `recipients`: string[] — Channel-specific recipients (optional)

## Outputs
- `alert_id`: string — Unique alert identifier
- `delivered`: boolean — Whether alert was sent
- `channels_sent`: string[] — Channels that received the alert
- `metadata`: object — Timestamp, retry status

## Steps
1. Validate channel and alert_type
2. Apply template for alert_type (trade, risk, etc.)
3. Format message for each channel (truncate for SMS, rich for Slack)
4. Route to notification-sender per channel
5. Log alert for audit trail
6. Return alert_id and delivery status

## Example
```
Input: channel="slack", alert_type="trade", title="Position Opened", body="AAPL 100 shares @ 175.50", priority="medium"
Output: {
  alert_id: "ALT-20250303-001",
  delivered: true,
  channels_sent: ["slack"],
  metadata: {sent_at: "2025-03-03T14:22:00Z"}
}
```

## Notes
- SMS has character limits; body is truncated automatically
- Critical alerts can bypass rate limits
- Integrates with notification-sender for actual delivery
