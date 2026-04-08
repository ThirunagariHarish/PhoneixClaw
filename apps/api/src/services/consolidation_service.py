"""
Nightly Consolidation Service — Phase 3 "Agent Sleep" pipeline.

Reads TRADE_OBSERVATION wiki entries from the last 30 days, finds repeating
patterns, writes/updates MARKET_PATTERNS and STRATEGY_LEARNINGS entries,
prunes stale knowledge, and proposes new rules.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.src.repositories.consolidation_repo import ConsolidationRepository
from apps.api.src.repositories.wiki_repo import WikiRepository
from shared.db.models.agent import Agent
from shared.db.models.consolidation import ConsolidationRun
from shared.db.models.wiki import AgentWikiEntry

logger = logging.getLogger(__name__)

PATTERN_KEYWORDS: dict[str, list[str]] = {
    "bearish_reversal": ["bearish", "reversal", "rejection", "fade"],
    "bullish_breakout": ["bullish", "breakout", "breakup", "momentum"],
    "support_hold": ["support", "bounce", "hold", "bottom"],
    "resistance_reject": ["resistance", "reject", "cap", "ceiling"],
    "volume_spike": ["volume", "spike", "surge", "flood"],
    "gap_fill": ["gap", "fill", "opening"],
}

# Thresholds for pattern detection
_MIN_OBSERVATIONS_FOR_PATTERN = 3
_MIN_CONFIDENCE_FOR_RULE = 0.80
_MIN_COUNT_FOR_RULE = 5
_STALE_DAYS = 90
_LOW_CONFIDENCE_THRESHOLD = 0.30


class ConsolidationService:
    """Orchestrates the nightly consolidation pipeline for a single agent."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.consolidation_repo = ConsolidationRepository(session)
        self.wiki_repo = WikiRepository(session)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run_consolidation(
        self,
        agent_id: UUID,
        run_id: UUID,
        run_type: str = "nightly",
    ) -> ConsolidationRun:
        """Main pipeline entry point.

        Updates the run record throughout execution.  Always commits a final
        status (completed or failed) so the run is never left as 'running'.
        """
        run = await self.consolidation_repo.update_status(
            run_id,
            "running",
            started_at=datetime.now(timezone.utc),
        )
        if run is None:
            raise RuntimeError(f"ConsolidationRun {run_id} not found")
        await self.session.commit()

        try:
            # Step 1 — load recent trade observations
            observations = await self._load_recent_trade_observations(agent_id)
            trades_analyzed = len(observations)

            # Step 2 — find patterns
            patterns = await self._find_patterns(observations)

            # Step 3 — write/update wiki pattern entries
            user_id = await self._get_agent_user_id(agent_id)
            entries_written, entries_updated = await self._write_pattern_entries(
                agent_id, user_id, patterns
            )

            # Step 4 — prune stale entries
            entries_pruned = await self._prune_stale_entries(agent_id)

            # Step 5 — propose rules
            rules_proposed = await self._propose_rules(agent_id, patterns)

            # Step 6 — generate report
            report = self._generate_report(
                agent_id=agent_id,
                trades_analyzed=trades_analyzed,
                patterns=patterns,
                entries_written=entries_written,
                entries_updated=entries_updated,
                entries_pruned=entries_pruned,
                rules_proposed=rules_proposed,
            )

            run = await self.consolidation_repo.update_status(
                run_id,
                "completed",
                completed_at=datetime.now(timezone.utc),
                trades_analyzed=trades_analyzed,
                wiki_entries_written=entries_written,
                wiki_entries_updated=entries_updated,
                wiki_entries_pruned=entries_pruned,
                patterns_found=len(patterns),
                rules_proposed=rules_proposed,
                consolidation_report=report,
            )
            await self.session.commit()
            logger.info(
                "[consolidation] agent=%s run=%s completed: %d obs, %d patterns, %d written, "
                "%d updated, %d pruned, %d rules",
                agent_id,
                run_id,
                trades_analyzed,
                len(patterns),
                entries_written,
                entries_updated,
                entries_pruned,
                rules_proposed,
            )
        except Exception as exc:
            logger.exception("[consolidation] agent=%s run=%s FAILED: %s", agent_id, run_id, exc)
            try:
                run = await self.consolidation_repo.update_status(
                    run_id,
                    "failed",
                    completed_at=datetime.now(timezone.utc),
                    error_message=str(exc)[:500],
                )
                await self.session.commit()
            except Exception:
                logger.exception("[consolidation] Could not persist failure status")

        return run  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Pipeline steps
    # ------------------------------------------------------------------

    async def _load_recent_trade_observations(self, agent_id: UUID) -> list[AgentWikiEntry]:
        """Load TRADE_OBSERVATION entries from the last 30 days."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        stmt = (
            select(AgentWikiEntry)
            .where(
                AgentWikiEntry.agent_id == agent_id,
                AgentWikiEntry.is_active.is_(True),
                AgentWikiEntry.category == "TRADE_OBSERVATION",
                AgentWikiEntry.created_at >= cutoff,
            )
            .order_by(desc(AgentWikiEntry.created_at))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def _find_patterns(self, observations: list[AgentWikiEntry]) -> list[dict]:
        """Group by symbol + keyword cluster.

        A pattern is detected when ≥3 observations share the same symbol AND
        match the same keyword cluster.  Returns a list of pattern dicts with:
            symbol, pattern_type, count, avg_confidence, sample_titles
        """
        # symbol → pattern_type → list[entry]
        grouped: dict[str, dict[str, list[AgentWikiEntry]]] = defaultdict(lambda: defaultdict(list))

        for obs in observations:
            symbols = list(obs.symbols or [])
            pattern_types = self._classify_observation(obs)
            if not pattern_types:
                continue
            for sym in symbols or ["_no_symbol"]:
                for pt in pattern_types:
                    grouped[sym][pt].append(obs)

        patterns = []
        for symbol, pt_map in grouped.items():
            for pattern_type, entries in pt_map.items():
                if len(entries) < _MIN_OBSERVATIONS_FOR_PATTERN:
                    continue
                avg_conf = sum(e.confidence_score for e in entries) / len(entries)
                patterns.append(
                    {
                        "symbol": symbol if symbol != "_no_symbol" else None,
                        "pattern_type": pattern_type,
                        "count": len(entries),
                        "avg_confidence": round(avg_conf, 3),
                        "sample_titles": [e.title for e in entries[:3]],
                        "entry_ids": [str(e.id) for e in entries],
                    }
                )
        return patterns

    async def _write_pattern_entries(
        self,
        agent_id: UUID,
        user_id: UUID | None,
        patterns: list[dict],
    ) -> tuple[int, int]:
        """Write or update MARKET_PATTERNS wiki entries for detected patterns.

        Returns (written, updated) counts.
        """
        written = 0
        updated = 0

        for pat in patterns:
            symbol = pat["symbol"] or "GENERAL"
            pattern_type = pat["pattern_type"]
            title = f"[Auto] {pattern_type.replace('_', ' ').title()} — {symbol}"

            content_lines = [
                "**Auto-generated by Nightly Consolidation** (run_type: nightly)",
                "",
                f"**Pattern:** {pattern_type}",
                f"**Symbol:** {symbol}",
                f"**Observations:** {pat['count']}",
                f"**Average Confidence:** {pat['avg_confidence']:.2f}",
                "",
                "**Sample titles from TRADE_OBSERVATION entries:**",
            ]
            for t in pat["sample_titles"]:
                content_lines.append(f"- {t}")
            content = "\n".join(content_lines)

            # Check if a MARKET_PATTERNS entry with this title already exists
            stmt = select(AgentWikiEntry).where(
                AgentWikiEntry.agent_id == agent_id,
                AgentWikiEntry.category == "MARKET_PATTERNS",
                AgentWikiEntry.title == title,
                AgentWikiEntry.is_active.is_(True),
            )
            result = await self.session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                await self.wiki_repo.update_entry(
                    existing,
                    {
                        "content": content,
                        "confidence_score": pat["avg_confidence"],
                        "symbols": [symbol] if symbol != "GENERAL" else [],
                        "change_reason": "nightly consolidation update",
                    },
                    updated_by="agent",
                )
                updated += 1
            else:
                data = {
                    "agent_id": agent_id,
                    "user_id": user_id,
                    "category": "MARKET_PATTERNS",
                    "subcategory": pattern_type,
                    "title": title,
                    "content": content,
                    "tags": ["auto", "consolidation", pattern_type],
                    "symbols": [symbol] if symbol != "GENERAL" else [],
                    "confidence_score": pat["avg_confidence"],
                    "trade_ref_ids": [],
                    "created_by": "agent",
                    "is_shared": True,
                }
                await self.wiki_repo.create_entry(data)
                written += 1

        return written, updated

    async def _prune_stale_entries(self, agent_id: UUID) -> int:
        """Soft-delete low-confidence entries older than _STALE_DAYS days.

        Targets TRADE_OBSERVATION entries only (auto-generated observations
        that haven't been promoted to patterns).
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=_STALE_DAYS)
        stmt = select(AgentWikiEntry).where(
            AgentWikiEntry.agent_id == agent_id,
            AgentWikiEntry.is_active.is_(True),
            AgentWikiEntry.category == "TRADE_OBSERVATION",
            AgentWikiEntry.confidence_score < _LOW_CONFIDENCE_THRESHOLD,
            AgentWikiEntry.created_at < cutoff,
        )
        result = await self.session.execute(stmt)
        stale_entries = list(result.scalars().all())
        for entry in stale_entries:
            await self.wiki_repo.soft_delete(entry)
        return len(stale_entries)

    async def _propose_rules(self, agent_id: UUID, patterns: list[dict]) -> int:
        """For high-confidence, high-count patterns, add a rule proposal to agent.pending_improvements."""
        eligible = [
            p
            for p in patterns
            if p["avg_confidence"] >= _MIN_CONFIDENCE_FOR_RULE and p["count"] >= _MIN_COUNT_FOR_RULE
        ]
        if not eligible:
            return 0

        agent = await self.session.get(Agent, agent_id)
        if not agent:
            return 0

        pending = dict(agent.pending_improvements or {})
        items: list[dict] = list(pending.get("items", []))

        added = 0
        for pat in eligible:
            symbol = pat["symbol"] or "any"
            rule_id = f"auto_rule_{pat['pattern_type']}_{symbol}"
            # Skip if already proposed
            if any(r.get("id") == rule_id for r in items):
                continue
            items.append(
                {
                    "id": rule_id,
                    "type": "pattern_rule",
                    "description": (
                        f"Add rule for {pat['pattern_type'].replace('_', ' ')} on {symbol} "
                        f"(n={pat['count']}, avg_conf={pat['avg_confidence']:.2f})"
                    ),
                    "backtest_status": "pending",
                    "source": "consolidation",
                    "pattern_type": pat["pattern_type"],
                    "symbol": symbol,
                    "count": pat["count"],
                    "avg_confidence": pat["avg_confidence"],
                }
            )
            added += 1

        if added > 0:
            pending["items"] = items
            agent.pending_improvements = pending
            await self.session.flush()

        return added

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _classify_observation(self, entry: AgentWikiEntry) -> list[str]:
        """Return list of matching pattern types for an observation."""
        text_combined = (entry.title + " " + entry.content).lower()
        return [pt for pt, kws in PATTERN_KEYWORDS.items() if any(kw in text_combined for kw in kws)]

    def _generate_report(
        self,
        agent_id: UUID,
        trades_analyzed: int,
        patterns: list[dict],
        entries_written: int,
        entries_updated: int,
        entries_pruned: int,
        rules_proposed: int,
    ) -> str:
        """Generate a Markdown consolidation report."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        lines = [
            "# Nightly Consolidation Report",
            "",
            f"**Agent:** `{agent_id}`  ",
            f"**Generated:** {now}",
            "",
            "## Summary",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Trades analyzed | {trades_analyzed} |",
            f"| Patterns detected | {len(patterns)} |",
            f"| Wiki entries written | {entries_written} |",
            f"| Wiki entries updated | {entries_updated} |",
            f"| Stale entries pruned | {entries_pruned} |",
            f"| Rules proposed | {rules_proposed} |",
            "",
        ]

        if patterns:
            lines += [
                "## Detected Patterns",
                "",
            ]
            for pat in patterns:
                symbol = pat["symbol"] or "—"
                lines += [
                    f"### {pat['pattern_type'].replace('_', ' ').title()} — {symbol}",
                    f"- **Count:** {pat['count']} observations",
                    f"- **Avg Confidence:** {pat['avg_confidence']:.2f}",
                    "- **Samples:**",
                ]
                for title in pat["sample_titles"]:
                    lines.append(f"  - {title}")
                lines.append("")
        else:
            lines += [
                "## Detected Patterns",
                "",
                f"_No patterns detected in this run (fewer than {_MIN_OBSERVATIONS_FOR_PATTERN} "
                f"matching observations per symbol/cluster)._",
                "",
            ]

        lines += [
            "---",
            "*Generated automatically by the Phoenix Nightly Consolidation Pipeline.*",
        ]
        return "\n".join(lines)

    async def _get_agent_user_id(self, agent_id: UUID) -> UUID | None:
        """Fetch the owning user_id for an agent."""
        agent = await self.session.get(Agent, agent_id)
        return agent.user_id if agent else None
