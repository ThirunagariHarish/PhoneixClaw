"""
Pydantic models for Unusual Whales API responses.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class OptionContract(BaseModel):
    ticker: str
    strike: float
    option_type: str = Field(description="CALL or PUT")
    expiration: str
    bid: float | None = None
    ask: float | None = None
    mid: float | None = None
    volume: int = 0
    open_interest: int = 0
    implied_volatility: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    iv_rank: float | None = None


class OptionsFlow(BaseModel):
    ticker: str
    strike: float
    option_type: str
    expiration: str
    sentiment: str | None = None
    volume: int = 0
    open_interest: int = 0
    premium: float | None = None
    trade_type: str | None = None  # sweep, block, split
    timestamp: datetime | None = None


class OptionChain(BaseModel):
    ticker: str
    contracts: list[OptionContract] = Field(default_factory=list)
    updated_at: datetime | None = None


class GexData(BaseModel):
    ticker: str
    total_gex: float | None = None
    call_gex: float | None = None
    put_gex: float | None = None
    gex_by_strike: dict[str, float] = Field(default_factory=dict)
    zero_gamma_level: float | None = None


class MarketTide(BaseModel):
    net_premium: float | None = None
    call_premium: float | None = None
    put_premium: float | None = None
    call_volume: int = 0
    put_volume: int = 0
    put_call_ratio: float | None = None
    timestamp: datetime | None = None


class ContractRecommendation(BaseModel):
    contract: OptionContract
    score: float = Field(ge=0, le=1, description="Confidence score 0-1")
    rationale: str = ""
    expected_return: float | None = None
    risk_level: str = "medium"  # low, medium, high
    max_loss_estimate: float | None = None


class AnalysisResult(BaseModel):
    ticker: str
    direction: str  # bullish / bearish
    top_contracts: list[ContractRecommendation] = Field(default_factory=list)
    multi_leg_suggestions: list[dict] = Field(default_factory=list)
    gex_data: GexData | None = None
    market_tide: MarketTide | None = None
    analysis_summary: str = ""
    timestamp: datetime | None = None
