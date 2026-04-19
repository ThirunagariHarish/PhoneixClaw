# Skill: Self Debugging

## Purpose
Enable the agent to diagnose and fix its own errors (code, logic, API calls) by analyzing stack traces, logs, and context to propose fixes.

## Triggers
- When the agent encounters an error or exception
- When user reports a bug or unexpected behavior
- When a skill or tool returns an error
- When validation or health checks fail

## Inputs
- `error`: string — Error message or stack trace
- `context`: object — Relevant context: skill name, inputs, recent actions
- `log_snippet`: string — Optional recent log lines
- `fix_scope`: string — "suggest", "apply", or "explain" — depth of intervention

## Outputs
- `diagnosis`: string — Root cause analysis
- `suggested_fix`: string — Proposed fix (code, config, or action)
- `confidence`: number — 0–1 confidence in diagnosis
- `applied`: boolean — Whether fix was applied (if fix_scope=apply)
- `metadata`: object — Error type, skill, timestamp

## Steps
1. Parse error message and stack trace
2. Extract error type, file, line number, and exception class
3. Load relevant code or config if path available
4. Analyze context: inputs, recent tool calls, state
5. Use LLM or rule-based logic to infer root cause
6. Propose fix: code patch, config change, or retry with different params
7. If fix_scope=apply: attempt to apply fix (with user approval if needed)
8. If fix_scope=explain: return diagnosis and explanation only
9. Return diagnosis, suggested_fix, confidence, applied status

## Example
```
Input: error="KeyError: 'symbol'", context={skill: "order-placer", inputs: {}}, fix_scope="suggest"
Output: {
  diagnosis: "order-placer expects intent.symbol but received intent without symbol key",
  suggested_fix: "Ensure intent object includes symbol field before calling order-placer",
  confidence: 0.9,
  applied: false,
  metadata: {error_type: "KeyError", skill: "order-placer", timestamp: "2025-03-03T15:00:00Z"}
}
```
