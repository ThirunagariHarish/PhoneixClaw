# Skill: Code Generator (Python)

## Purpose
Generate Python code (strategies, indicators, scripts) from natural language or structured specs for backtesting, analysis, or automation.

## Triggers
- When the agent needs to generate trading or analysis code
- When user requests a script, indicator, or strategy implementation
- When building custom indicators or backtest logic
- When automating repetitive code patterns

## Inputs
- `prompt`: string — Natural language description of desired code
- `template`: string — Optional template type: "indicator", "strategy", "script", "test"
- `constraints`: object — Optional: max_lines, libraries_allowed, style
- `context`: object — Optional: existing code, imports, dependencies

## Outputs
- `code`: string — Generated Python code
- `explanation`: string — Brief explanation of generated logic
- `dependencies`: string[] — Required imports or packages
- `metadata`: object — Template used, prompt_hash, generated_at

## Steps
1. Parse prompt and template; resolve constraints
2. Build system prompt with style guide, safety rules (no exec of user input)
3. Include context (existing code, imports) if provided
4. Call LLM to generate code; request Python only
5. Validate syntax (ast.parse); fix common errors if needed
6. Extract imports and dependencies from generated code
7. Add docstring or explanation from LLM response
8. Return code, explanation, dependencies
9. Do not execute generated code; user must review before run

## Example
```
Input: prompt="RSI indicator with 14 period, return oversold when <30 and overbought when >70", template="indicator"
Output: {
  code: "def rsi(prices, period=14):\n    ...",
  explanation: "Computes RSI using Wilder smoothing; flags oversold/overbought.",
  dependencies: ["numpy"],
  metadata: {template: "indicator", generated_at: "2025-03-03T15:00:00Z"}
}
```
