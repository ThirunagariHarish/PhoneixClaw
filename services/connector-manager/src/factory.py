"""
Connector factory — creates connector instances by type.

M1.9: Factory pattern for connector instantiation.
Reference: ImplementationPlan.md Section 1 (Factory pattern).
"""

from typing import Any

from services.connector_manager.src.base import BaseConnector, ConnectorType

_REGISTRY: dict[ConnectorType, type[BaseConnector]] = {}


def register_connector(connector_type: ConnectorType):
    """Decorator to register a connector class in the factory."""
    def wrapper(cls: type[BaseConnector]):
        _REGISTRY[connector_type] = cls
        return cls
    return wrapper


def create_connector(connector_type: str, connector_id: str, config: dict[str, Any]) -> BaseConnector:
    """
    Create a connector instance by type string.
    
    Raises ValueError if the connector type is not registered.
    """
    try:
        ct = ConnectorType(connector_type)
    except ValueError:
        raise ValueError(
            f"Unknown connector type '{connector_type}'. "
            f"Available: {[t.value for t in ConnectorType]}"
        )

    cls = _REGISTRY.get(ct)
    if cls is None:
        raise ValueError(
            f"Connector type '{connector_type}' is recognized but has no registered implementation."
        )

    return cls(connector_id=connector_id, config=config)


def list_available_connectors() -> list[dict[str, str]]:
    """List all registered connector types with their implementation status."""
    result = []
    for ct in ConnectorType:
        result.append({
            "type": ct.value,
            "implemented": ct in _REGISTRY,
        })
    return result
