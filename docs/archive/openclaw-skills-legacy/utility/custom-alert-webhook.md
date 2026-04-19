# Custom Alert Webhook

## Purpose
Send signals to TradingView, Discord, or any webhook endpoint for alerts and integrations.

## Category
utility

## Triggers
- When trade signal is generated (entry, exit, stop)
- When user configures webhook for symbol or strategy
- When alert condition is met (price level, indicator threshold)
- When integrating with external platforms (TradingView, Discord, Slack)

## Inputs
- `signal`: object — {symbol, side, action, price, rationale, strategy_id}
- `webhook_config`: object — {url, method, headers, format}
- `destinations`: string[] — ["tradingview", "discord", "slack", "custom"]
- `template`: string — Optional; custom message template (default: JSON or platform-specific)
- `filters`: object — Optional; only send if symbol in list, or strategy matches

## Outputs
- `delivered`: boolean — True if webhook responded 2xx
- `response_status`: number — HTTP status from endpoint
- `response_body`: string — Optional; response for debugging
- `delivery_time_ms`: number — Round-trip time
- `errors`: string[] — Any delivery failures

## Steps
1. Load webhook_config for each destination
2. Format signal per destination: TradingView (JSON), Discord (embed), Slack (blocks)
3. Apply filters if configured (symbol, strategy)
4. POST to webhook URL with appropriate headers and body
5. Record response_status, response_body, delivery_time_ms
6. On failure: retry once; log to errors
7. Return delivered, response_status, response_body, delivery_time_ms, errors
8. Support batch: multiple signals in one webhook call if configured

## Example
```
Input: signal={symbol:"AAPL",side:"BUY",action:"ENTRY",price:178.50,rationale:"breakout"}, 
       webhook_config={url:"https://discord.com/api/webhooks/...", format:"discord"}
Output: {
  delivered: true,
  response_status: 204,
  response_body: "",
  delivery_time_ms: 120,
  errors: []
}
```

## Notes
- Never log webhook URLs or secrets; redact in audit
- Rate limit outbound webhooks to avoid blocking
- TradingView webhooks expect specific JSON; see TradingView docs
