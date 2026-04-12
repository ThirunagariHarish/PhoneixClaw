"""Auto-Research Self-Improvement Loop (Phase 4d).

Karpathy-style daily self-improvement where agents analyze their own
performance and update their knowledge base and instructions.

Orchestrated by the ScheduledAgentRunner for the supervisor type.
Can also be triggered manually via API.

5-step cycle:
  1. Gather performance data (Python, $0)
  2. Analyze patterns (LLM via ModelRouter, ~$0.02)
  3. Write wiki entries (Python, $0)
  4. Update agent instructions (Python, $0)
  5. Trigger retraining if needed (Python, $0)
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


async def run_auto_research(agent_id: uuid.UUID | None = None) -> dict:
    """Run the full auto-research loop for one agent or all active agents.

    Returns a summary dict with findings and actions taken.
    """
    results = []

    if agent_id:
        result = await _research_agent(agent_id)
        results.append(result)
    else:
        agent_ids = await _get_active_agents()
        for aid in agent_ids:
            try:
                result = await _research_agent(aid)
                results.append(result)
            except Exception as e:
                logger.error("Auto-research failed for agent %s: %s", aid, e)
                results.append({"agent_id": str(aid), "status": "error", "error": str(e)[:200]})

    return {
        "agents_analyzed": len(results),
        "improvements_found": sum(1 for r in results if r.get("improvements")),
        "wiki_entries_created": sum(r.get("wiki_entries_created", 0) for r in results),
        "retrain_triggered": sum(1 for r in results if r.get("retrain_triggered")),
        "results": results,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def _get_active_agents() -> list[uuid.UUID]:
    """Get all agents with status RUNNING or PAPER."""
    try:
        from sqlalchemy import select

        from shared.db.engine import get_session
        from shared.db.models.agent import Agent

        async for db in get_session():
            stmt = select(Agent.id).where(Agent.status.in_(["RUNNING", "PAPER"]))
            rows = (await db.execute(stmt)).all()
            return [row[0] for row in rows]
    except Exception as e:
        logger.error("Failed to get active agents: %s", e)
        return []


async def _research_agent(agent_id: uuid.UUID) -> dict:
    """Run the 5-step auto-research loop for a single agent."""
    logger.info("Auto-research starting for agent %s", agent_id)

    # Step 1: Gather performance data
    perf_data = await _gather_performance(agent_id)
    if not perf_data.get("trades"):
        return {
            "agent_id": str(agent_id),
            "status": "skipped",
            "reason": "No trades in the last 24h",
        }

    # Step 2: Analyze patterns via LLM
    analysis = await _analyze_patterns(agent_id, perf_data)

    # Step 3: Write wiki entries
    wiki_count = await _write_wiki_entries(agent_id, analysis)

    # Step 4: Update agent instructions
    instruction_updates = await _update_instructions(agent_id, analysis)

    # Step 5: Check retrain trigger
    retrain_triggered = await _check_retrain_trigger(agent_id, perf_data)

    return {
        "agent_id": str(agent_id),
        "status": "completed",
        "trades_analyzed": len(perf_data.get("trades", [])),
        "win_rate": perf_data.get("win_rate"),
        "improvements": analysis.get("improvements", []),
        "wiki_entries_created": wiki_count,
        "instruction_updates": instruction_updates,
        "retrain_triggered": retrain_triggered,
    }


async def _gather_performance(agent_id: uuid.UUID) -> dict:
    """Step 1: Query all trades from the last 24h and compute metrics."""
    try:
        from sqlalchemy import select

        from shared.db.engine import get_session
        from shared.db.models.agent_trade import AgentTrade

        since = datetime.now(timezone.utc) - timedelta(days=1)

        async for db in get_session():
            stmt = select(AgentTrade).where(
                AgentTrade.agent_id == agent_id,
                AgentTrade.created_at >= since,
            )
            rows = (await db.execute(stmt)).scalars().all()

            trades = []
            wins = 0
            total_pnl = 0.0

            for t in rows:
                trade_data = {
                    "ticker": t.ticker,
                    "side": t.side,
                    "entry_price": float(t.entry_price) if t.entry_price else 0,
                    "exit_price": float(t.exit_price) if t.exit_price else 0,
                    "status": t.status,
                    "model_confidence": float(t.model_confidence) if t.model_confidence else 0,
                    "reasoning": t.reasoning or "",
                }
                trades.append(trade_data)

                if t.exit_price and t.entry_price:
                    pnl = float(t.exit_price) - float(t.entry_price)
                    if t.side == "sell":
                        pnl = -pnl
                    total_pnl += pnl
                    if pnl > 0:
                        wins += 1

            closed = [t for t in trades if t.get("exit_price", 0) > 0]
            win_rate = (wins / len(closed) * 100) if closed else 0

            return {
                "trades": trades,
                "total_trades": len(trades),
                "closed_trades": len(closed),
                "win_rate": round(win_rate, 1),
                "total_pnl": round(total_pnl, 2),
                "avg_confidence": round(
                    sum(t["model_confidence"] for t in trades) / len(trades), 2
                ) if trades else 0,
            }
    except Exception as e:
        logger.error("Failed to gather performance for %s: %s", agent_id, e)
        return {"trades": []}


async def _analyze_patterns(agent_id: uuid.UUID, perf_data: dict) -> dict:
    """Step 2: Use LLM to analyze trading patterns and suggest improvements."""
    from shared.utils.model_router import get_router

    router = get_router(agent_id=agent_id)

    trades_summary = json.dumps(perf_data["trades"][:20], default=str)[:3000]

    prompt = f"""Analyze these trading results from the last 24 hours:

Win rate: {perf_data['win_rate']}%
Total P&L: ${perf_data['total_pnl']}
Trades: {perf_data['total_trades']} ({perf_data['closed_trades']} closed)
Average model confidence: {perf_data['avg_confidence']}

Recent trades:
{trades_summary}

Identify:
1. What patterns led to winning trades?
2. What patterns led to losing trades?
3. Which model predictions were wrong?
4. 2-3 specific improvements to the trading strategy.

Reply with a JSON object:
{{
    "patterns": {{"winning": [...], "losing": [...]}},
    "model_issues": [...],
    "improvements": [
        {{"title": "...", "description": "...", "priority": "high/medium/low"}}
    ]
}}"""

    try:
        resp = await router.complete(
            task_type="auto_research",
            prompt=prompt,
            system="You are a quantitative trading analyst reviewing an AI agent's performance. Be specific and data-driven.",
            temperature=0.3,
            max_tokens=1024,
            json_mode=True,
        )
        return json.loads(resp.text)
    except json.JSONDecodeError:
        return {"patterns": {}, "model_issues": [], "improvements": []}
    except Exception as e:
        logger.error("LLM analysis failed for %s: %s", agent_id, e)
        return {"patterns": {}, "model_issues": [], "improvements": []}


async def _write_wiki_entries(agent_id: uuid.UUID, analysis: dict) -> int:
    """Step 3: Persist analysis as AgentWikiEntry records."""
    entries_created = 0

    try:
        from sqlalchemy import select

        from shared.db.engine import get_session
        from shared.db.models.wiki import AgentWikiEntry

        improvements = analysis.get("improvements", [])
        patterns = analysis.get("patterns", {})

        today = date.today().isoformat()

        async for db in get_session():
            # Dedup: check if we already have a self_improvement entry for today
            existing = (await db.execute(
                select(AgentWikiEntry.id).where(
                    AgentWikiEntry.agent_id == agent_id,
                    AgentWikiEntry.tags.contains(["self_improvement"]),
                    AgentWikiEntry.title.contains(today),
                )
            )).first()

            if existing:
                logger.info("Wiki entry already exists for %s on %s, skipping", agent_id, today)
                return 0

            # Write improvements as wiki entries
            for imp in improvements[:3]:
                entry = AgentWikiEntry(
                    agent_id=agent_id,
                    category="STRATEGY_LEARNINGS",
                    subcategory="auto_research",
                    title=f"[{today}] {imp.get('title', 'Improvement')}",
                    content=imp.get("description", ""),
                    tags=["self_improvement", "auto_research", today],
                    confidence_score=0.7,
                )
                db.add(entry)
                entries_created += 1

            # Write pattern discoveries
            for pattern_type in ("winning", "losing"):
                pattern_list = patterns.get(pattern_type, [])
                if pattern_list:
                    content = "\n".join(f"- {p}" for p in pattern_list[:5])
                    entry = AgentWikiEntry(
                        agent_id=agent_id,
                        category="MARKET_PATTERNS",
                        subcategory=f"{pattern_type}_patterns",
                        title=f"[{today}] {pattern_type.capitalize()} patterns identified",
                        content=content,
                        tags=["auto_research", "pattern_discovery", pattern_type, today],
                        confidence_score=0.6,
                    )
                    db.add(entry)
                    entries_created += 1

            if entries_created > 0:
                await db.commit()

    except Exception as e:
        logger.error("Failed to write wiki entries for %s: %s", agent_id, e)

    return entries_created


async def _update_instructions(agent_id: uuid.UUID, analysis: dict) -> list[str]:
    """Step 4: Append specific rules to the agent's CLAUDE.md if patterns are strong."""
    updates = []
    improvements = analysis.get("improvements", [])

    high_priority = [imp for imp in improvements if imp.get("priority") == "high"]
    if not high_priority:
        return updates

    try:
        from sqlalchemy import select

        from shared.db.engine import get_session
        from shared.db.models.agent import Agent

        async for db in get_session():
            agent = (await db.execute(
                select(Agent).where(Agent.id == agent_id)
            )).scalar_one_or_none()

            if not agent or not agent.work_dir:
                return updates

            claude_md = Path(agent.work_dir) / "CLAUDE.md"
            if not claude_md.exists():
                return updates

            existing_content = claude_md.read_text()
            today = date.today().isoformat()
            marker = f"## Auto-Research Rules ({today})"

            if marker in existing_content:
                return ["already_updated"]

            new_rules = [f"\n\n{marker}\n"]
            for imp in high_priority[:2]:
                rule = f"- {imp['title']}: {imp['description']}"
                new_rules.append(rule)
                updates.append(imp["title"])

            claude_md.write_text(existing_content + "\n".join(new_rules) + "\n")
            logger.info("Updated CLAUDE.md for agent %s with %d rules", agent_id, len(updates))

    except Exception as e:
        logger.error("Failed to update instructions for %s: %s", agent_id, e)

    return updates


async def _check_retrain_trigger(agent_id: uuid.UUID, perf_data: dict) -> bool:
    """Step 5: Flag agent for re-backtesting if accuracy drops below threshold."""
    ACCURACY_THRESHOLD = 60.0

    win_rate = perf_data.get("win_rate", 100)
    if win_rate >= ACCURACY_THRESHOLD or perf_data.get("closed_trades", 0) < 5:
        return False

    logger.warning(
        "Agent %s win rate %.1f%% below threshold %.1f%% — flagging for retrain",
        agent_id, win_rate, ACCURACY_THRESHOLD,
    )

    try:
        from sqlalchemy import select

        from shared.db.engine import get_session
        from shared.db.models.agent import Agent

        async for db in get_session():
            agent = (await db.execute(
                select(Agent).where(Agent.id == agent_id)
            )).scalar_one_or_none()

            if agent:
                manifest = agent.manifest or {}
                manifest["retrain_requested"] = True
                manifest["retrain_reason"] = f"Win rate {win_rate}% below {ACCURACY_THRESHOLD}%"
                manifest["retrain_requested_at"] = datetime.now(timezone.utc).isoformat()
                agent.manifest = manifest
                await db.commit()
                return True
    except Exception as e:
        logger.error("Failed to flag retrain for %s: %s", agent_id, e)

    return False
