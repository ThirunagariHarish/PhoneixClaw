# Self-Updating Prompt

## Purpose
Agent modifies its own system prompt based on performance data to improve over time.

## Category
advanced-ai

## Triggers
- After vector-db-retrospective or post-trade-retrospective completes
- On schedule (e.g., weekly) when sufficient new performance data exists
- When user approves prompt update (optional approval gate)
- When adversarial-red-team suggests hardening changes

## Inputs
- `current_prompt`: string — Existing system prompt
- `performance_data`: object — {win_rate, avg_hold, failure_patterns, improvement_suggestions}
- `update_rules`: object — Constraints (max_length, forbidden_phrases, required_sections)
- `approval_required`: boolean — If true, return draft for human review (default: true)

## Outputs
- `new_prompt`: string — Proposed updated prompt
- `diff`: object — {added: string[], removed: string[], modified: string[]}
- `rationale`: string — Why each change was made
- `status`: string — "DRAFT" | "APPROVED" | "REJECTED" (if approval_required)

## Steps
1. Load current_prompt and performance_data
2. Extract failure_patterns and improvement_suggestions
3. Use LLM to generate new_prompt: incorporate fixes, preserve required sections
4. Validate against update_rules (length, forbidden phrases)
5. Compute diff between current and new prompt
6. Generate rationale for each change
7. If approval_required: return status=DRAFT, await human approval
8. On approval: persist new_prompt; return status=APPROVED
9. Return new_prompt, diff, rationale, status

## Example
```
Input: current_prompt="You are a swing trader...", performance_data={failure_patterns: ["late_exit"], improvement_suggestions: ["Tighten trailing stop"]},
       approval_required=true
Output: {
  new_prompt: "You are a swing trader... [ADDED: Exit within 2 ATR of peak. Never hold through VIX spike.]",
  diff: {added: ["Exit within 2 ATR of peak"], removed: [], modified: ["exit rules"]},
  rationale: "Late exits caused 12% of losses. Added explicit ATR-based exit rule.",
  status: "DRAFT"
}
```

## Notes
- Always require human approval for production; avoid runaway changes
- Version and backup prompts before updates; allow rollback
- Integrate with adversarial-red-team to validate updates don't introduce vulnerabilities
