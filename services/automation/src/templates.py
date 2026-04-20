"""
Pre-built automation templates.

M3.5: Automations.
"""
from __future__ import annotations

from services.automation.src.scheduler import AUTOMATION_TEMPLATES


def get_template_by_id(template_id: str) -> dict | None:
    for t in AUTOMATION_TEMPLATES:
        if t["id"] == template_id:
            return dict(t)
    return None


def list_templates() -> list[dict]:
    return [dict(t) for t in AUTOMATION_TEMPLATES]


def instantiate_template(template_id: str, overrides: dict | None = None) -> dict | None:
    """Create an automation config from a template with optional overrides."""
    tpl = get_template_by_id(template_id)
    if not tpl:
        return None
    if overrides:
        tpl.update(overrides)
    return tpl
