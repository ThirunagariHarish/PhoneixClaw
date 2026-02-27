"""
Strategy Agent — OpenClaw-inspired autonomous trading strategy builder.

Features:
  - Iterative ReAct (Reason + Act) agent loop with tool-result feedback
  - SSE streaming for real-time step updates to the frontend
  - Modular tool registry with real implementations
  - Persistent per-user memory
  - Error recovery and self-correction
  - Approval gates for high-risk actions (deploy)
"""

import asyncio
import json
import logging
import re
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel
from starlette.responses import StreamingResponse

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))

from shared.graceful_shutdown import shutdown
from shared.llm.client import OllamaClient
from shared.metrics import create_metrics_route

import services.strategy_agent.src.tools.market  # noqa: F401 — registers tools
import services.strategy_agent.src.tools.strategy  # noqa: F401 — registers tools
from services.strategy_agent.src.tools import (
    TOOL_DESCRIPTIONS,
    build_tool_descriptions_text,
    execute_tool,
)
from services.strategy_agent.src.memory import AgentMemory

SERVICE_NAME = "strategy-agent"
logger = logging.getLogger(SERVICE_NAME)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

MAX_ITERATIONS = 8
MAX_RETRIES_PER_TOOL = 2


# ── Models ────────────────────────────────────────────────────────────────────

class ParseRequest(BaseModel):
    strategy_text: str


class BacktestRequest(BaseModel):
    strategy_text: str
    parsed_config: dict = {}
    ticker: str = "SPY"
    period_years: int = 2


class AgentChatRequest(BaseModel):
    message: str
    conversation_history: list[dict] = []
    strategy_context: dict | None = None
    user_id: str = "anonymous"


# ── App ───────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("%s ready (OpenClaw-style ReAct agent)", SERVICE_NAME)
    yield
    await shutdown.run_cleanup()


app = FastAPI(title=SERVICE_NAME, lifespan=lifespan)
create_metrics_route(app)


@app.get("/health")
async def health():
    return {"status": "ready", "service": SERVICE_NAME, "mode": "react-agent"}


# ── Legacy endpoints (kept for backward compat) ──────────────────────────────

@app.post("/parse")
async def parse(req: ParseRequest):
    from services.strategy_agent.src.parser import parse_strategy
    result = await parse_strategy(req.strategy_text)
    return {"parsed_config": result}


@app.post("/backtest")
async def backtest(req: BacktestRequest):
    from services.strategy_agent.src.backtest_engine import run_backtest
    from services.strategy_agent.src.benchmark_comparer import compare_with_benchmarks
    from services.strategy_agent.src.data_fetcher import fetch_historical_data
    from services.strategy_agent.src.parser import parse_strategy
    from services.strategy_agent.src.report_generator import generate_report

    config = req.parsed_config
    if not config:
        config = await parse_strategy(req.strategy_text)

    ticker = config.get("ticker") or req.ticker
    data = await fetch_historical_data(ticker, req.period_years)

    if data.empty:
        return {"error": f"No historical data available for {ticker}"}

    backtest_result = run_backtest(data, config)
    benchmarks = await compare_with_benchmarks(backtest_result, ticker, req.period_years)
    report = await generate_report(req.strategy_text, config, backtest_result, benchmarks)

    return {
        "strategy_text": req.strategy_text,
        "parsed_config": config,
        "ticker": ticker,
        "report": report,
    }


# ── ReAct System Prompt ──────────────────────────────────────────────────────

def build_system_prompt(memory_context: str = "") -> str:
    tools_text = build_tool_descriptions_text()
    memory_block = f"\n\nMEMORY CONTEXT:\n{memory_context}" if memory_context else ""

    return f"""\
You are an autonomous trading strategy agent operating in a ReAct (Reason + Act) loop.
You can call tools across multiple iterations. After each tool result, you re-evaluate and decide the next step.

{tools_text}

RESPONSE FORMAT:
For each step, output a THOUGHT line followed by an ACTION line:

THOUGHT: <your reasoning about what to do next>
ACTION: {{"tool": "tool_name", "params": {{...}}}}

When you have enough information and want to reply to the user, use the respond tool:
THOUGHT: I have all the information. Let me summarize for the user.
ACTION: {{"tool": "respond", "params": {{"message": "..."}}}}

RULES:
- You MUST end with a "respond" action
- You may call multiple tools across multiple rounds before responding
- After seeing a tool result (OBSERVATION), reason about it in your next THOUGHT
- Be proactive: if the user says "create a strategy", build one immediately — don't ask clarifying questions
- After creating a strategy, automatically parse and backtest it
- Report results concisely with key metrics (return %, Sharpe ratio, max drawdown, win rate)
- Suggest improvements based on backtest results
- If a tool fails, try an alternative approach in your next iteration
- The deploy tool requires user approval — inform the user and wait for confirmation
- Use analyze_sentiment and fetch_market_data to gather context before making strategy decisions{memory_block}"""


# ── Agent Loop (non-streaming, backward compat) ──────────────────────────────

@app.post("/agent/chat")
async def agent_chat(req: AgentChatRequest):
    """ReAct agent loop — iterates up to MAX_ITERATIONS, feeding tool results back to the LLM."""
    steps, final_message = await _run_agent_loop(req)
    return {
        "message": final_message,
        "steps": steps,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ── SSE Streaming Agent Endpoint ─────────────────────────────────────────────

@app.post("/agent/chat/stream")
async def agent_chat_stream(req: AgentChatRequest):
    """SSE streaming endpoint — sends each agent step as a server-sent event in real time."""
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def run_agent():
        try:
            _, final_message = await _run_agent_loop(
                req,
                stream_callback=lambda step: queue.put_nowait(
                    f"data: {json.dumps(step)}\n\n"
                ),
            )
            queue.put_nowait(f"data: {json.dumps({'type': 'done', 'message': final_message})}\n\n")
        except Exception as e:
            queue.put_nowait(f"data: {json.dumps({'type': 'error', 'content': str(e)[:200]})}\n\n")
        finally:
            queue.put_nowait(None)

    async def generate():
        task = asyncio.create_task(run_agent())
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield event
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(generate(), media_type="text/event-stream")


# ── Core Agent Loop ──────────────────────────────────────────────────────────

async def _run_agent_loop(
    req: AgentChatRequest,
    stream_callback=None,
) -> tuple[list[dict], str]:
    """
    Core ReAct agent loop.

    1. Build messages with system prompt + memory + conversation history
    2. Call LLM
    3. Parse THOUGHT + ACTION from response
    4. Execute tool, append OBSERVATION
    5. Repeat until "respond" action or MAX_ITERATIONS
    """
    llm = OllamaClient()
    memory = AgentMemory(req.user_id)

    memory_context = memory.build_context_block(
        strategies=req.strategy_context.get("strategies") if req.strategy_context else None
    )
    system_prompt = build_system_prompt(memory_context)

    messages: list[dict] = [{"role": "system", "content": system_prompt}]

    for msg in req.conversation_history[-20:]:
        messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})

    if req.strategy_context:
        ctx_str = json.dumps(req.strategy_context, indent=2)
        messages.append({"role": "system", "content": f"Current session context:\n{ctx_str}"})

    messages.append({"role": "user", "content": req.message})

    steps: list[dict] = []
    final_message = ""
    tool_retry_counts: dict[str, int] = {}

    for iteration in range(MAX_ITERATIONS):
        logger.info("Agent iteration %d/%d", iteration + 1, MAX_ITERATIONS)

        try:
            response = await llm.chat(
                messages=messages,
                temperature=0.4,
                json_mode=False,
            )
            raw_text = response.text if hasattr(response, "text") else str(response)
        except Exception as e:
            logger.exception("LLM call failed on iteration %d", iteration + 1)
            error_step = {"type": "error", "content": f"LLM error: {str(e)[:200]}"}
            steps.append(error_step)
            if stream_callback:
                stream_callback(error_step)
            break

        if not raw_text or not raw_text.strip():
            raw_text = _generate_fallback(req.message)

        thought, actions = _parse_react_response(raw_text)

        if thought:
            thinking_step = {"type": "thinking", "content": thought, "iteration": iteration + 1}
            steps.append(thinking_step)
            if stream_callback:
                stream_callback(thinking_step)

        if not actions:
            final_message = raw_text
            break

        done = False
        for action in actions:
            tool_name = action.get("tool", "")
            params = action.get("params", {})

            if tool_name == "respond":
                final_message = params.get("message", "")
                resp_step = {"type": "response", "content": final_message}
                steps.append(resp_step)
                if stream_callback:
                    stream_callback(resp_step)
                done = True
                break

            requires_approval = any(
                t["name"] == tool_name and t.get("requires_approval")
                for t in TOOL_DESCRIPTIONS
            )

            if requires_approval:
                approval_step = {
                    "type": "approval_required",
                    "tool": tool_name,
                    "params": params,
                    "content": f"The '{tool_name}' action requires your approval before proceeding.",
                }
                steps.append(approval_step)
                if stream_callback:
                    stream_callback(approval_step)
                messages.append({
                    "role": "assistant",
                    "content": f"THOUGHT: The {tool_name} tool requires user approval. I'll inform the user.\n"
                               f'ACTION: {{"tool": "respond", "params": {{"message": "I need your approval to deploy this strategy. '
                               f'Please click Approve to proceed or Reject to cancel."}}}}',
                })
                final_message = (
                    f"I need your approval to deploy this strategy. "
                    f"Please click **Approve** to proceed or **Reject** to cancel."
                )
                done = True
                break

            thinking_step = {"type": "thinking", "content": f"Executing {tool_name}...", "iteration": iteration + 1}
            steps.append(thinking_step)
            if stream_callback:
                stream_callback(thinking_step)

            result = await execute_tool(tool_name, params)

            if "error" in result:
                retry_key = tool_name
                tool_retry_counts[retry_key] = tool_retry_counts.get(retry_key, 0) + 1

                error_step = {
                    "type": "action",
                    "tool": tool_name,
                    "status": "error",
                    "error": result["error"],
                    "iteration": iteration + 1,
                }
                steps.append(error_step)
                if stream_callback:
                    stream_callback(error_step)

                if tool_retry_counts[retry_key] < MAX_RETRIES_PER_TOOL:
                    messages.append({
                        "role": "assistant",
                        "content": f"THOUGHT: Let me call {tool_name}.\nACTION: {json.dumps(action)}",
                    })
                    messages.append({
                        "role": "user",
                        "content": f"OBSERVATION: Tool '{tool_name}' failed with error: {result['error']}. "
                                   f"Try a different approach or alternative parameters.",
                    })
                    continue
                else:
                    messages.append({
                        "role": "assistant",
                        "content": f"THOUGHT: Let me call {tool_name}.\nACTION: {json.dumps(action)}",
                    })
                    messages.append({
                        "role": "user",
                        "content": f"OBSERVATION: Tool '{tool_name}' failed after retries: {result['error']}. "
                                   f"Skip this step and continue with what you have.",
                    })
                    continue

            success_step = {
                "type": "action",
                "tool": tool_name,
                "status": "success",
                "result": result,
                "iteration": iteration + 1,
            }
            steps.append(success_step)
            if stream_callback:
                stream_callback(success_step)

            messages.append({
                "role": "assistant",
                "content": f"THOUGHT: {thought or 'Let me proceed.'}\nACTION: {json.dumps(action)}",
            })

            result_summary = json.dumps(result, default=str)
            if len(result_summary) > 2000:
                result_summary = result_summary[:2000] + "... (truncated)"

            messages.append({
                "role": "user",
                "content": f"OBSERVATION: {result_summary}",
            })

        if done:
            break

    if not final_message:
        final_message = "I've completed the analysis. Let me know if you'd like me to do anything else."

    if not steps or steps[-1].get("type") != "response":
        resp_step = {"type": "response", "content": final_message}
        steps.append(resp_step)
        if stream_callback:
            stream_callback(resp_step)

    try:
        strategy_names = [
            s.get("result", {}).get("name", "")
            for s in steps
            if s.get("tool") == "create_strategy" and s.get("status") == "success"
        ]
        memory.append_summary(
            summary=f"User: {req.message[:100]}... -> Agent: {final_message[:100]}...",
            strategies_mentioned=strategy_names,
        )
        memory.extract_and_save_facts_from_conversation(
            [{"role": "user", "content": req.message}] + req.conversation_history[-5:]
        )
    except Exception:
        logger.debug("Memory save failed (non-critical)")

    return steps, final_message


# ── Response Parsing ─────────────────────────────────────────────────────────

def _parse_react_response(text: str) -> tuple[str, list[dict]]:
    """
    Parse a ReAct-format response into (thought, actions).

    Handles multiple formats:
      1. THOUGHT: ... ACTION: {...}     (ReAct format)
      2. [{"tool": "...", ...}]         (JSON array)
      3. {"tool": "...", ...}           (single JSON object)
      4. Plain text                     (treated as final response)
    """
    text = text.strip()
    thought = ""
    actions = []

    thought_match = re.search(r"THOUGHT:\s*(.+?)(?=\nACTION:|$)", text, re.DOTALL)
    if thought_match:
        thought = thought_match.group(1).strip()

    action_matches = list(re.finditer(r"ACTION:\s*(\{.+?\})(?:\s*(?:THOUGHT|ACTION|$))", text, re.DOTALL))
    if action_matches:
        for m in action_matches:
            try:
                action = json.loads(m.group(1))
                if isinstance(action, dict) and "tool" in action:
                    actions.append(action)
            except json.JSONDecodeError:
                continue

    if not actions:
        action_match = re.search(r"ACTION:\s*(\{.+\})", text, re.DOTALL)
        if action_match:
            try:
                action = json.loads(action_match.group(1))
                if isinstance(action, dict) and "tool" in action:
                    actions = [action]
            except json.JSONDecodeError:
                pass

    if not actions:
        json_start = text.find("[")
        json_end = text.rfind("]") + 1
        if json_start >= 0 and json_end > json_start:
            try:
                parsed = json.loads(text[json_start:json_end])
                if isinstance(parsed, list):
                    actions = [a for a in parsed if isinstance(a, dict) and "tool" in a]
                    if not thought and json_start > 0:
                        thought = text[:json_start].strip()
            except json.JSONDecodeError:
                pass

    if not actions:
        json_start = text.find("{")
        json_end = text.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            try:
                action = json.loads(text[json_start:json_end])
                if isinstance(action, dict) and "tool" in action:
                    actions = [action]
                    if not thought and json_start > 0:
                        thought = text[:json_start].strip()
            except json.JSONDecodeError:
                pass

    if not actions:
        actions = [{"tool": "respond", "params": {"message": text}}]
        if not thought:
            thought = ""

    return thought, actions


# ── Fallback ─────────────────────────────────────────────────────────────────

def _generate_fallback(message: str) -> str:
    """Generate a ReAct-formatted fallback when LLM is unavailable."""
    msg_lower = message.lower()

    if any(w in msg_lower for w in ["create", "build", "make", "new", "design"]):
        tickers = re.findall(r"\b([A-Z]{1,5})\b", message)
        ticker = tickers[0] if tickers else "SPY"
        action = json.dumps({"tool": "create_strategy", "params": {
            "name": f"Strategy for {ticker}",
            "strategy_text": message[:200],
            "ticker": ticker,
        }})
        return (
            f"THOUGHT: The user wants to create a new strategy for {ticker}. "
            f"I'll create it, parse the rules, and run a backtest.\n"
            f"ACTION: {action}"
        )

    if any(w in msg_lower for w in ["backtest", "test", "run", "simulate"]):
        action = json.dumps({"tool": "backtest", "params": {
            "strategy_text": message[:200],
            "ticker": "SPY",
            "period_years": 2,
        }})
        return (
            f"THOUGHT: The user wants to run a backtest.\n"
            f"ACTION: {action}"
        )

    if any(w in msg_lower for w in ["sentiment", "mood", "feeling"]):
        tickers = re.findall(r"\b([A-Z]{1,5})\b", message)
        ticker = tickers[0] if tickers else "SPY"
        return (
            f"THOUGHT: The user wants sentiment analysis for {ticker}.\n"
            f'ACTION: {{"tool": "analyze_sentiment", "params": {{"ticker": "{ticker}"}}}}'
        )

    if any(w in msg_lower for w in ["portfolio", "positions", "holdings"]):
        return (
            "THOUGHT: The user wants to see their portfolio.\n"
            'ACTION: {"tool": "analyze_portfolio", "params": {}}'
        )

    return (
        "THOUGHT: The user has a general question. Let me respond helpfully.\n"
        'ACTION: {"tool": "respond", "params": {"message": '
        '"I\'m your autonomous strategy agent. Here\'s what I can do:\\n\\n'
        "- **Create** strategies from natural language\\n"
        "- **Backtest** against historical market data\\n"
        "- **Analyze sentiment** from Discord and news feeds\\n"
        "- **Fetch market data** with technical indicators\\n"
        "- **Check your portfolio** positions and P&L\\n"
        "- **Deploy** strategies to live trading (with approval)\\n\\n"
        'Just tell me what you\'d like to do!"}}'
    )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8025)
