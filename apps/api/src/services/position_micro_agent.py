"""Position Monitor Micro-Agent (Tier 1 + Tier 2).

Replaces the full Claude SDK session for position monitoring with:
  - Tier 1: Python asyncio loop running TA calculations directly
  - Tier 2: Cheap OpenRouter LLM call for exit reasoning

Spawned by the analyst agent via execute_trade.py -> Phoenix API.
Tracked in AgentSession like any other agent.

Cost: ~$0.0001 per check (~$0.07/day per position) vs $5-10/day with SDK.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

INITIAL_FAST_INTERVAL = 30
INITIAL_FAST_DURATION = 300  # 5 minutes
NORMAL_INTERVAL = 120
URGENT_INTERVAL = 30
URGENCY_THRESHOLD = 50
AFTER_HOURS_INTERVAL = 900  # 15 min outside market hours


class PositionMicroAgent:
    """Lightweight position monitor: Python TA + OpenRouter LLM for exit reasoning."""

    def __init__(
        self,
        agent_id: uuid.UUID,
        session_id: uuid.UUID,
        position: dict,
        config: dict,
        work_dir: Path,
        analyst_patterns: dict | None = None,
    ):
        self.agent_id = agent_id
        self.session_id = session_id
        self.ticker = position.get("ticker", "")
        self.side = position.get("side", "buy")
        self.entry_price = float(position.get("entry_price", 0))
        self.quantity = float(position.get("quantity", 0))
        self.position = position
        self.config = config
        self.work_dir = work_dir
        self.analyst_patterns = analyst_patterns or {}
        self.active = True
        self.sell_signals: list[dict] = []
        self._check_count = 0
        self._start_time = datetime.now(timezone.utc)
        self._last_decision: dict = {}
        self._router = None

    async def _get_router(self):
        if self._router is None:
            from shared.utils.model_router import get_router
            self._router = get_router(agent_id=self.agent_id)
        return self._router

    async def run(self) -> dict:
        """Main loop: check position, reason, act."""
        logger.info(
            "PositionMicroAgent started: %s %s %.1f @ $%.2f (session=%s)",
            self.side, self.ticker, self.quantity, self.entry_price, self.session_id,
        )

        try:
            while self.active:
                self._check_count += 1
                try:
                    decision = await self._check_cycle()
                    self._last_decision = decision

                    await self._report_heartbeat(decision)

                    if decision.get("action") in ("FULL_EXIT", "SELL"):
                        logger.info(
                            "MicroAgent %s: EXIT decision for %s — %s",
                            self.session_id, self.ticker, decision.get("reasoning", ""),
                        )
                        execution = await self._execute_exit(decision)
                        await self._report_close(decision, execution)
                        return {"status": "closed", "decision": decision, "execution": execution}

                except Exception as e:
                    logger.error("MicroAgent %s check cycle failed: %s", self.session_id, e)

                interval = self._compute_interval()
                await asyncio.sleep(interval)

        except asyncio.CancelledError:
            logger.info("MicroAgent %s cancelled", self.session_id)
            return {"status": "cancelled"}

        return {"status": "stopped"}

    async def _check_cycle(self) -> dict:
        """One check iteration: TA (Python) + analyst prediction + reasoning (LLM)."""
        # Tier 1: Run exit_decision.py to get TA indicators and urgency score
        ta_result = await self._run_exit_decision()

        urgency = ta_result.get("urgency", 0)
        action = ta_result.get("action", "HOLD")
        current_price = ta_result.get("current_price", 0)

        # Analyst exit prediction: exit_decision.py includes it when analyst_exit_profile exists
        if "analyst_exit_prediction" in ta_result:
            analyst_pred = ta_result["analyst_exit_prediction"]
        else:
            analyst_pred = self._predict_analyst_exit(current_price)
            ta_result["analyst_exit_prediction"] = analyst_pred
            if analyst_pred.get("probability", 0) > 70:
                urgency += 20
                ta_result["urgency"] = min(urgency, 100)
            elif analyst_pred.get("probability", 0) > 50:
                urgency += 10
                ta_result["urgency"] = min(urgency, 100)

        # Time-series exit awareness
        time_urgency = self._compute_time_awareness()
        if time_urgency > 0:
            urgency += time_urgency
            ta_result["urgency"] = min(urgency, 100)
            ta_result.setdefault("time_signals", {}).update(self._last_time_signals)

        # If urgency > 80 or stop loss hit, skip LLM reasoning and exit immediately
        if urgency >= 80 or action == "FULL_EXIT":
            return ta_result

        # If urgency is low and no sell signals, skip LLM to save tokens
        if urgency < 20 and not self.sell_signals and self._check_count % 5 != 0:
            return ta_result

        # Tier 2: LLM reasoning for nuanced decisions
        try:
            llm_decision = await self._llm_reason(ta_result)
            if llm_decision.get("action") in ("SELL", "FULL_EXIT"):
                ta_result["action"] = llm_decision["action"]
                ta_result["llm_reasoning"] = llm_decision.get("reasoning", "")
                ta_result["urgency"] = max(urgency, 80)
        except Exception as e:
            logger.debug("LLM reasoning failed (non-fatal, using TA only): %s", e)

        return ta_result

    def _predict_analyst_exit(self, current_price: float | None) -> dict:
        """Use the analyst exit predictor to estimate exit probability."""
        if not self.analyst_patterns:
            return {"probability": 0, "reasons": ["no_analyst_profile"]}
        try:
            from shared.utils.analyst_exit_predictor import predict_analyst_exit
            return predict_analyst_exit(
                profile=self.analyst_patterns,
                position=self.position,
                current_price=current_price,
            )
        except Exception as e:
            logger.debug("Analyst exit prediction failed: %s", e)
            return {"probability": 0, "reasons": [f"error: {e}"]}

    _last_time_signals: dict = {}

    def _compute_time_awareness(self) -> int:
        """Time-series exit awareness: overstay, Friday risk, power hour."""
        urgency = 0
        signals: dict = {}

        now = datetime.now(timezone.utc)
        et_hour = (now.hour - 4) % 24  # approximate ET
        today_dow = now.weekday()

        # Overstay detection (2x analyst avg hold)
        avg_hold = (self.analyst_patterns or {}).get("avg_hold_hours")
        if avg_hold:
            entry_time = self.position.get("entry_time") or self.position.get("opened_at")
            if entry_time:
                if isinstance(entry_time, str):
                    try:
                        entry_time = datetime.fromisoformat(entry_time)
                    except ValueError:
                        entry_time = None
                if entry_time:
                    if entry_time.tzinfo is None:
                        entry_time = entry_time.replace(tzinfo=timezone.utc)
                    hold_hours = (now - entry_time).total_seconds() / 3600
                    if hold_hours > avg_hold * 2:
                        urgency += 15
                        signals["overstay"] = f"held {hold_hours:.1f}h vs avg {avg_hold:.1f}h"

        # Friday afternoon risk (options)
        if today_dow == 4 and et_hour >= 14:
            urgency += 10
            signals["friday_risk"] = f"Friday {et_hour}:00 ET"
            # Extra urgency if holding options expiring this week
            expiry = self.position.get("expiry")
            if expiry:
                from datetime import date as date_cls
                if isinstance(expiry, str):
                    try:
                        expiry = date_cls.fromisoformat(expiry)
                    except ValueError:
                        expiry = None
                if expiry and (expiry - now.date()).days <= 1:
                    urgency += 10
                    signals["expiry_imminent"] = f"expires {expiry}"

        # Power hour (3-4 PM ET): increase responsiveness
        if 15 <= et_hour < 16:
            signals["power_hour"] = True
            # No urgency bump, but the interval computation handles this

        self._last_time_signals = signals
        return urgency

    async def _run_exit_decision(self) -> dict:
        """Run the existing exit_decision.py tool as a subprocess."""
        exit_script = self.work_dir / "tools" / "exit_decision.py"
        if not exit_script.exists():
            logger.warning("exit_decision.py not found at %s, using fallback", exit_script)
            return await self._fallback_ta()

        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, str(exit_script),
                "--position-id", self.ticker,
                "--output", str(self.work_dir / "last_decision.json"),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.work_dir),
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)

            if proc.returncode == 0 and stdout:
                return json.loads(stdout.decode())
        except asyncio.TimeoutError:
            logger.warning("exit_decision.py timed out for %s", self.ticker)
        except (json.JSONDecodeError, Exception) as e:
            logger.warning("exit_decision.py failed for %s: %s", self.ticker, e)

        return await self._fallback_ta()

    async def _fallback_ta(self) -> dict:
        """Minimal TA when exit_decision.py is unavailable."""
        try:
            import yfinance as yf
            data = yf.download(self.ticker, period="1d", interval="1m", progress=False)
            if not data.empty:
                if hasattr(data.columns, "levels"):
                    data.columns = data.columns.get_level_values(0)
                current = float(data["Close"].iloc[-1])
                pnl = (current - self.entry_price) / self.entry_price * 100
                return {
                    "action": "HOLD",
                    "urgency": 0,
                    "ticker": self.ticker,
                    "current_price": current,
                    "entry_price": self.entry_price,
                    "pnl_pct": round(pnl, 2),
                    "reasoning": "Fallback TA only (exit_decision.py unavailable)",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
        except Exception:
            pass

        return {
            "action": "HOLD",
            "urgency": 0,
            "ticker": self.ticker,
            "reasoning": "No price data available",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def _llm_reason(self, ta_result: dict) -> dict:
        """Use OpenRouter LLM for nuanced exit reasoning."""
        router = await self._get_router()

        sell_signal_context = ""
        if self.sell_signals:
            recent = self.sell_signals[-3:]
            sell_signal_context = f"\nAnalyst sell signals received: {json.dumps(recent, default=str)}"

        pattern_context = ""
        if self.analyst_patterns:
            pattern_context = f"\nAnalyst historical patterns: {json.dumps(self.analyst_patterns, default=str)[:500]}"

        # Analyst exit prediction context
        exit_pred_context = ""
        pred = ta_result.get("analyst_exit_prediction", {})
        if pred.get("probability", 0) > 0:
            exit_pred_context = (
                f"\nAnalyst exit probability: {pred['probability']}%"
                f"\nAnalyst exit reasons: {', '.join(pred.get('reasons', []))}"
            )

        # Time-series awareness context
        time_context = ""
        time_sigs = ta_result.get("time_signals", {})
        if time_sigs:
            time_context = f"\nTime signals: {json.dumps(time_sigs, default=str)}"

        prompt = f"""You are a position monitoring agent for {self.ticker}.

Position: {self.side.upper()} {self.quantity} @ ${self.entry_price}
Current price: ${ta_result.get('current_price', '?')}
P&L: {ta_result.get('pnl_pct', '?')}%
TA urgency score: {ta_result.get('urgency', 0)}/100
TA reasoning: {ta_result.get('reasoning', 'N/A')}
TA indicators: {json.dumps(ta_result.get('ta_indicators', {}), default=str)[:300]}
{sell_signal_context}{pattern_context}{exit_pred_context}{time_context}

Based on ALL the above, should you HOLD or SELL? Reply with ONLY a JSON object:
{{"action": "HOLD" or "SELL", "reasoning": "brief explanation"}}"""

        resp = await router.complete(
            task_type="exit_decision",
            prompt=prompt,
            temperature=0.3,
            max_tokens=200,
            json_mode=True,
        )

        try:
            return json.loads(resp.text)
        except json.JSONDecodeError:
            text = resp.text.strip()
            if "SELL" in text.upper():
                return {"action": "SELL", "reasoning": text[:200]}
            return {"action": "HOLD", "reasoning": text[:200]}

    async def _execute_exit(self, decision: dict) -> dict:
        """Execute the position close via the MCP client."""
        exit_pct = decision.get("suggested_exit_pct", 100)
        qty_to_exit = max(1, int(self.quantity * exit_pct / 100))

        # Call the robinhood_mcp.py tool directly
        rh_script = self.work_dir / "tools" / "robinhood_mcp.py"
        if not rh_script.exists():
            rh_script = (
                Path(__file__).resolve().parents[4]
                / "agents" / "templates" / "live-trader-v1" / "tools" / "robinhood_mcp.py"
            )

        try:
            env = {
                "HOME": str(self.work_dir),
                "PATH": "/usr/local/bin:/usr/bin:/bin",
            }
            creds = self.config.get("robinhood_credentials", self.config.get("robinhood", {}))
            if isinstance(creds, dict):
                env["RH_USERNAME"] = creds.get("username", "")
                env["RH_PASSWORD"] = creds.get("password", "")
                env["RH_TOTP_SECRET"] = creds.get("totp_secret", "")
            if self.config.get("paper_mode"):
                env["PAPER_MODE"] = "true"

            # Start MCP server and send close_position command
            proc = await asyncio.create_subprocess_exec(
                sys.executable, str(rh_script),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=str(self.work_dir),
            )

            # Send initialize + tools/call close_position
            init_msg = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}) + "\n"
            close_msg = json.dumps({
                "jsonrpc": "2.0", "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "close_position",
                    "arguments": {"ticker": self.ticker, "quantity": qty_to_exit},
                },
            }) + "\n"

            stdout, _ = await asyncio.wait_for(
                proc.communicate(input=(init_msg + close_msg).encode()),
                timeout=60,
            )

            for line in stdout.decode().strip().split("\n"):
                try:
                    resp = json.loads(line)
                    if resp.get("id") == 2:
                        content = resp.get("result", {}).get("content", [{}])
                        if content:
                            return json.loads(content[0].get("text", "{}"))
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue

            return {"executed": False, "error": "no_response_from_mcp"}
        except Exception as e:
            logger.error("Exit execution failed for %s: %s", self.ticker, e)
            return {"executed": False, "error": str(e)[:200]}

    def receive_sell_signal(self, signal: dict) -> None:
        """Called by the gateway when the analyst routes a sell signal."""
        self.sell_signals.append({
            **signal,
            "received_at": datetime.now(timezone.utc).isoformat(),
        })
        # Write to workspace so exit_decision.py can also read it
        sell_path = self.work_dir / "sell_signal.json"
        try:
            sell_path.write_text(json.dumps(signal, indent=2, default=str))
        except Exception:
            pass

    def _compute_interval(self) -> float:
        """Adaptive check interval based on urgency, market hours, and power hour."""
        elapsed = (datetime.now(timezone.utc) - self._start_time).total_seconds()

        # Fast checks in first 5 minutes
        if elapsed < INITIAL_FAST_DURATION:
            return INITIAL_FAST_INTERVAL

        # Check market hours
        try:
            from shared.utils.market_calendar import is_market_open
            if not is_market_open():
                return AFTER_HOURS_INTERVAL
        except ImportError:
            pass

        # Power hour (3-4 PM ET): use faster checks
        now = datetime.now(timezone.utc)
        et_hour = (now.hour - 4) % 24
        if 15 <= et_hour < 16:
            return URGENT_INTERVAL

        # Adaptive based on last urgency
        last_urgency = self._last_decision.get("urgency", 0)
        if last_urgency >= URGENCY_THRESHOLD:
            return URGENT_INTERVAL

        # Also check analyst exit probability for adaptive interval
        pred = self._last_decision.get("analyst_exit_prediction", {})
        if pred.get("probability", 0) > 60:
            return URGENT_INTERVAL

        return NORMAL_INTERVAL

    async def _report_heartbeat(self, decision: dict) -> None:
        """Update session heartbeat in the database with market session context."""
        # Fetch market status (with graceful fallback)
        market_context = self._get_market_context()

        # Enrich the decision dict with market fields for downstream consumers
        decision["market_session"] = market_context["market_session"]
        decision["regular_session_open"] = market_context["regular_session_open"]
        decision["extended_hours_open"] = market_context["extended_hours_open"]
        decision["is_trading_day"] = market_context["is_trading_day"]
        decision["next_regular_open"] = market_context["next_regular_open"]

        try:
            from sqlalchemy import update

            from shared.db.engine import get_session
            from shared.db.models.agent_session import AgentSession

            now = datetime.now(timezone.utc)
            heartbeat_data = {
                "last_heartbeat_context": {
                    "ticker": self.ticker,
                    "check_count": self._check_count,
                    "action": decision.get("action", "HOLD"),
                    "urgency": decision.get("urgency", 0),
                    "pnl_pct": decision.get("pnl_pct"),
                    **market_context,
                    "timestamp": now.isoformat(),
                },
            }

            async for db in get_session():
                # Merge heartbeat_data into existing config JSONB
                await db.execute(
                    update(AgentSession)
                    .where(AgentSession.id == self.session_id)
                    .values(
                        last_heartbeat=now,
                        status="running",
                        config=AgentSession.config.concat(heartbeat_data),
                    )
                )
                await db.commit()
        except Exception as e:
            logger.debug("Heartbeat config update failed, falling back to simple heartbeat: %s", e)
            # Fall back to simple heartbeat without config update
            try:
                from sqlalchemy import update as _update

                from shared.db.engine import get_session as _get_session
                from shared.db.models.agent_session import AgentSession as _AgentSession

                async for db in _get_session():
                    await db.execute(
                        _update(_AgentSession)
                        .where(_AgentSession.id == self.session_id)
                        .values(
                            last_heartbeat=datetime.now(timezone.utc),
                            status="running",
                        )
                    )
                    await db.commit()
            except Exception:
                pass

    def _get_market_context(self) -> dict:
        """Retrieve market session data with graceful fallback on errors."""
        try:
            from shared.utils.market_calendar import get_market_status
            status = get_market_status()
            return {
                "market_session": status["session"],
                "regular_session_open": status["regular_session_open"],
                "extended_hours_open": status["extended_session_open"],
                "is_trading_day": status["is_trading_day"],
                "next_regular_open": status["next_regular_open_et"],
            }
        except Exception as e:
            logger.debug("get_market_status() failed, using defaults: %s", e)
            return {
                "market_session": "unknown",
                "regular_session_open": False,
                "extended_hours_open": False,
                "is_trading_day": False,
                "next_regular_open": None,
            }

    async def _report_close(self, decision: dict, execution: dict) -> None:
        """Report position close to Phoenix API and update session status."""
        try:
            from sqlalchemy import update

            from shared.db.engine import get_session
            from shared.db.models.agent_session import AgentSession

            async for db in get_session():
                await db.execute(
                    update(AgentSession)
                    .where(AgentSession.id == self.session_id)
                    .values(
                        status="completed",
                        completed_at=datetime.now(timezone.utc),
                    )
                )
                await db.commit()
        except Exception as e:
            logger.debug("Close report failed (non-fatal): %s", e)

        # Write final result
        try:
            result_path = self.work_dir / "final_decision.json"
            result_path.write_text(json.dumps({
                "decision": decision,
                "execution": execution,
                "closed_at": datetime.now(timezone.utc).isoformat(),
            }, indent=2, default=str))
        except Exception:
            pass

    def stop(self) -> None:
        self.active = False
