# Voice Command Trading

## Purpose
Process voice commands like "Exit all Apple positions now" for hands-free trading control.

## Category
utility

## Triggers
- When user speaks command via voice input (mobile, desktop, or device)
- When voice assistant or app captures trading intent
- For accessibility or quick action during volatile markets
- When user enables voice control in settings

## Inputs
- `audio_input`: object — Raw audio or speech-to-text transcript
- `stt_provider`: string — "whisper", "google", "azure" (default: whisper)
- `allowed_commands`: string[] — ["exit", "close", "cancel", "status", "pause"]
- `require_confirmation`: boolean — Echo back and confirm before execution (default: true)
- `user_id`: string — For auth and audit

## Outputs
- `transcript`: string — Recognized speech text
- `parsed_command`: object — {action, symbol, scope, params}
- `confirmation_required`: boolean — True if dangerous and require_confirmation
- `execution_result`: object — {success, message, trade_ids} after execution
- `audit_log`: object — Full chain for compliance

## Steps
1. If audio_input: run STT (Whisper, Google, Azure) to get transcript
2. Parse transcript: extract action (exit, close, cancel), symbol (Apple, AAPL), scope (all, half)
3. Map "Apple" -> AAPL, "all" -> full position; validate against allowed_commands
4. If require_confirmation: speak/display "Exit all AAPL positions. Confirm?" 
5. On confirmation: execute via execution layer (exit positions)
6. Return transcript, parsed_command, execution_result, audit_log
7. Log to audit for compliance; support natural-language-query for "Why did you exit?"

## Example
```
Input: audio_input={raw: "..."}, transcript="Exit all Apple positions now", require_confirmation=true
Output: {
  transcript: "Exit all Apple positions now",
  parsed_command: {action: "exit", symbol: "AAPL", scope: "all", params: {}},
  confirmation_required: true,
  execution_result: {success: true, message: "Closed 150 shares AAPL at 178.42", trade_ids: ["T-001"]},
  audit_log: {user_id: "U1", command: "exit_all_AAPL", executed_at: "2025-03-03T14:30:00Z"}
}
```

## Notes
- Restrict dangerous commands (e.g., no "buy 10000 shares" without extra auth)
- Use hitl-discord-confirm for large notional even with voice
- Consider wake word and speaker verification for security
