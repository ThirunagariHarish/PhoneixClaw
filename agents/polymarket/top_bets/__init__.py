"""agents.polymarket.top_bets — Scorer Chain + Agent loop for prediction markets (Phase 15.4–15.5).

Public exports:
    ReferenceClassScorer, ReferenceClassResult
    CoTSampler, CoTResult
    DebateScorer, DebateResult
    LLMScorer, LLMScorerResult
    TopBetScorer, ScoredMarket
    ModelEvaluator
    TopBetsAgent, CycleResult         (Phase 15.5)
    AutoResearchAgent, ResearchResult (Phase 15.5)
"""

from agents.polymarket.top_bets.agent import CycleResult, TopBetsAgent
from agents.polymarket.top_bets.auto_research import AutoResearchAgent, ResearchResult
from agents.polymarket.top_bets.cot_sampler import CoTResult, CoTSampler
from agents.polymarket.top_bets.debate_scorer import DebateResult, DebateScorer
from agents.polymarket.top_bets.llm_scorer import LLMScorer, LLMScorerResult
from agents.polymarket.top_bets.model_evaluator import ModelEvaluator
from agents.polymarket.top_bets.reference_class import ReferenceClassResult, ReferenceClassScorer
from agents.polymarket.top_bets.scorer import ScoredMarket, TopBetScorer

__all__ = [
    "AutoResearchAgent",
    "CoTResult",
    "CoTSampler",
    "CycleResult",
    "DebateResult",
    "DebateScorer",
    "LLMScorer",
    "LLMScorerResult",
    "ModelEvaluator",
    "ReferenceClassResult",
    "ReferenceClassScorer",
    "ResearchResult",
    "ScoredMarket",
    "TopBetScorer",
    "TopBetsAgent",
]
