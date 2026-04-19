# Audit Log PDF

## Purpose
Generate readable PDF of internal agent dialogue and decision chain for compliance and review.

## Category
utility

## Triggers
- On user request for audit report (date range, symbol, agent)
- After trade execution for compliance trail
- On schedule (e.g., daily or weekly summary)
- When regulator or internal audit requires documentation

## Inputs
- `date_range`: object — {start: ISO date, end: ISO date}
- `agent_id`: string — Optional; filter by agent
- `symbol`: string — Optional; filter by symbol
- `include_raw_logs`: boolean — Include full JSON logs (default: false)
- `output_path`: string — Where to save PDF (default: audits/audit_YYYYMMDD.pdf)

## Outputs
- `pdf_path`: string — Path to generated PDF file
- `summary`: object — {n_decisions, n_trades, date_range, agents_included}
- `sections`: string[] — Section headers in PDF (e.g., Decisions, Trades, Agent Dialogue)

## Steps
1. Query audit store for logs in date_range; filter by agent_id, symbol
2. Group by decision_id or trade_id; order chronologically
3. Build sections: Executive Summary, Decision Chain, Agent Dialogue, Trade Log
4. Format each decision: timestamp, agent, action, rationale, confidence (if agent-confidence-scorer)
5. Render to PDF using reportlab, weasyprint, or similar
6. Save to output_path; return pdf_path, summary, sections
7. Optionally email or upload to compliance system

## Example
```
Input: date_range={start:"2025-03-01", end:"2025-03-03"}, agent_id="daily-signals", output_path="audits/audit_20250303.pdf"
Output: {
  pdf_path: "audits/audit_20250303.pdf",
  summary: {n_decisions: 47, n_trades: 12, date_range: "2025-03-01..2025-03-03", agents_included: ["daily-signals"]},
  sections: ["Executive Summary", "Decision Chain", "Agent Dialogue", "Trade Log"]
}
```

## Notes
- Ensure PII and sensitive keys are redacted in PDF
- PDF should be tamper-evident; consider checksum or signing
- Integrate with agent-confidence-scorer to include confidence in decision chain
