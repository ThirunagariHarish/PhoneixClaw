# Telegram Strategy Builder

## Purpose
Create trading rules via natural language Telegram chat for rapid strategy prototyping.

## Category
utility

## Triggers
- When user sends strategy definition in Telegram
- When building rules from conversational flow ("When RSI < 30, buy")
- When user wants to edit or clone existing strategy via chat
- When integrating Telegram bot with strategy config store

## Inputs
- `message`: string — User message from Telegram
- `chat_id`: string — Telegram chat ID for replies
- `existing_strategy`: object — Optional; strategy to edit or clone
- `strategy_schema`: object — Valid rule structure (conditions, actions, params)
- `llm_provider`: string — For parsing natural language (default: gpt-4o)

## Outputs
- `parsed_strategy`: object — Structured strategy config (conditions, actions)
- `validation_errors`: string[] — Schema or logic errors
- `confirmation_message`: string — Human-readable summary to send back
- `strategy_id`: string — ID of created/updated strategy
- `status`: string — "CREATED" | "UPDATED" | "INVALID" | "PENDING_CONFIRM"

## Steps
1. Receive message; extract intent (create, edit, delete, list)
2. Use LLM to parse natural language into structured rules (e.g., "RSI < 30" -> {indicator: "RSI", op: "<", value: 30})
3. Map to strategy_schema: conditions (entry/exit), actions (buy/sell/size)
4. Validate: check indicator names, operators, required fields
5. If valid: save to strategy store; return strategy_id, status=CREATED/UPDATED
6. Build confirmation_message: "Created strategy: Buy when RSI < 30, exit when RSI > 70"
7. Send confirmation_message to chat_id via Telegram API
8. Return parsed_strategy, validation_errors, confirmation_message, strategy_id, status

## Example
```
Input: message="When RSI drops below 30 and volume is 2x average, buy 100 shares. Exit when RSI > 70.", chat_id="12345"
Output: {
  parsed_strategy: {conditions: [{indicator: "RSI", op: "<", value: 30}, {indicator: "volume_ratio", op: ">", value: 2}], action: {type: "buy", size: 100}, exit: {indicator: "RSI", op: ">", value: 70}},
  validation_errors: [],
  confirmation_message: "Created: Buy 100 when RSI<30 and volume 2x avg. Exit when RSI>70.",
  strategy_id: "strat-telegram-001",
  status: "CREATED"
}
```

## Notes
- Require explicit confirmation before activating live strategy
- Support "show my strategies" and "delete strategy X" commands
- Integrate with custom-alert-webhook to push signals to Telegram
