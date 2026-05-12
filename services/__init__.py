"""Phoenix v2 services package.

Hyphen-named service dirs (e.g. ``agent-comm``) can't be imported
directly as Python identifiers.  This module transparently maps
underscore names to their hyphen counterparts so that
``from services.agent_comm.src.protocol import ...`` resolves to
``services/agent-comm/src/protocol.py`` on disk.
"""
from __future__ import annotations

import importlib.abc
import importlib.machinery
import importlib.util
import os
import sys

_ALIASES: dict[str, str] = {
    "agent_comm": "agent-comm",
    "agent_orchestrator": "agent-orchestrator",
    "backtest_runner": "backtest-runner",
    "backtest_worker": "backtest-worker",
    "broker_gateway": "broker-gateway",
    "connector_manager": "connector-manager",
    "discord_ingestion": "discord-ingestion",
    "feature_extraction": "feature-extraction",
    "feature_pipeline": "feature-pipeline",
    "global_monitor": "global-monitor",
    "inference_service": "inference-service",
    "message_ingestion": "message-ingestion",
    "pipeline_worker": "pipeline-worker",
    "position_monitor": "position-monitor",
    "prediction_monitor": "prediction-monitor",
}

_SERVICES_DIR = os.path.dirname(os.path.abspath(__file__))


class _HyphenServiceFinder(importlib.abc.MetaPathFinder):
    """Resolve ``services.<underscore>.*`` to ``services/<hyphen>/`` on disk."""

    def find_spec(
        self,
        fullname: str,
        path: object = None,
        target: object = None,
    ) -> importlib.machinery.ModuleSpec | None:
        parts = fullname.split(".")
        if len(parts) < 2 or parts[0] != "services" or parts[1] not in _ALIASES:
            return None

        hyphen = _ALIASES[parts[1]]
        disk_path = os.path.join(_SERVICES_DIR, hyphen, *parts[2:])

        if os.path.isdir(disk_path):
            pkg_init = os.path.join(disk_path, "__init__.py")
            if os.path.isfile(pkg_init):
                return importlib.util.spec_from_file_location(
                    fullname,
                    pkg_init,
                    submodule_search_locations=[disk_path],
                )
            return importlib.machinery.ModuleSpec(
                fullname,
                None,
                is_package=True,
            )

        py_file = disk_path + ".py"
        if os.path.isfile(py_file):
            return importlib.util.spec_from_file_location(fullname, py_file)

        return None


_finder = _HyphenServiceFinder()
if not any(isinstance(f, _HyphenServiceFinder) for f in sys.meta_path):
    sys.meta_path.insert(0, _finder)
