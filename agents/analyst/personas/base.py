"""Persona configuration dataclass for analyst agents."""
from dataclasses import dataclass, field


@dataclass
class PersonaConfig:
    """Configuration for an analyst agent persona."""

    id: str
    name: str
    emoji: str
    description: str
    system_prompt_snippet: str
    tool_weights: dict[str, float]  # chart, options_flow, dark_pool, sentiment (must sum to 1.0)
    min_confidence_threshold: int   # 0-100
    preferred_timeframes: list[str]
    stop_loss_style: str            # 'tight' | 'standard' | 'wide'
    entry_style: str                # 'aggressive' | 'patient' | 'breakout'
    signal_filters: dict = field(default_factory=dict)

    def stop_loss_pct(self) -> float:
        """Return stop loss percentage based on style."""
        return {"tight": 1.0, "standard": 2.0, "wide": 4.0}[self.stop_loss_style]
