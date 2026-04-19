# Log Structured Output

## Purpose
Produce structured JSON log entries from agent actions for auditability and replay.

## Category
utility

## Triggers
- After every agent action or decision
- On error or exception within agent workflow

## Inputs
- action_type: The type of action performed (string)
- context: Contextual data about the action (dict)
- result: Outcome of the action (any)

## Outputs
- log_entry: Structured JSON log with timestamp, agent_id, action, context, result (dict)
- log_id: Unique identifier for the log entry (string)

## Steps
1. Capture current timestamp in ISO 8601 format
2. Collect agent identifier and session context
3. Serialize action type, input context, and result into structured JSON
4. Assign unique log ID (UUID v4)
5. Write to agent_logs table and stdout for container log collection
6. If error, include stack trace and severity level

## Example
Agent places a trade intent — log entry captures the intent ID, symbol, side, quantity, reasoning chain, and execution result in a single structured JSON record.

## Notes
- All logs are searchable via Loki in the observability stack
- Log levels: DEBUG, INFO, WARN, ERROR, CRITICAL
- Sensitive data (credentials, full API keys) must be redacted before logging
