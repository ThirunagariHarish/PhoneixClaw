import json
import logging

from shared.llm.client import OllamaClient

logger = logging.getLogger(__name__)

PARSE_PROMPT = """\
You are a trading strategy parser. \
Convert the user's natural language strategy description into a structured JSON format.

Output JSON with these fields:
- "name": short strategy name
- "asset_type": "equity" or "option"
- "ticker": primary ticker symbol (or null for multi-ticker)
- "direction": "long", "short", or "both"
- "entry_rules": list of conditions for entry
- "exit_rules": list of conditions for exit
- "filters": list of filtering conditions
- "time_constraints": any time-related constraints
- "position_sizing": position sizing rules
- "needs_clarification": list of questions if anything is ambiguous

Strategy description: {strategy_text}

Return ONLY valid JSON, no explanation."""


async def parse_strategy(strategy_text: str) -> dict:
    """Use LLM to parse a natural language strategy into structured config."""
    try:
        llm = OllamaClient()
        prompt = PARSE_PROMPT.format(strategy_text=strategy_text)
        response = await llm.generate(
            prompt=prompt,
            system="You are a quantitative trading strategy parser. Output only valid JSON.",
        )

        json_start = response.find("{")
        json_end = response.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            parsed = json.loads(response[json_start:json_end])
            return parsed
        return {"error": "Could not parse strategy", "raw_response": response}
    except Exception:
        logger.exception("Strategy parsing failed")
        return {
            "name": "Unnamed Strategy",
            "entry_rules": [strategy_text],
            "exit_rules": [],
            "filters": [],
            "needs_clarification": ["Could not automatically parse. Please refine your strategy description."],
        }
