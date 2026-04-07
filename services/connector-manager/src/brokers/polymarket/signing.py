"""CLOB signing helpers (Phase 2 stub).

The full L2 signature/EIP-712 logic lives inside py-clob-client. This module
exists as the single seam where private-key material is read from the
encrypted credential store and handed to the signer. Phase 2 only needs the
seam to exist so that later phases (order paths) can land here without
touching the rest of the connector.

CRITICAL: never log `private_key` or `api_secret`. Callers must redact.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ClobCredentials:
    """Decrypted Polymarket CLOB credentials.

    `private_key` is the EOA key used for L1 (allowance) operations.
    `api_key` / `api_secret` / `api_passphrase` are the L2 CLOB API
    credentials issued by Polymarket after the initial L1 handshake.
    """

    private_key: str
    api_key: str
    api_secret: str
    api_passphrase: str
    chain_id: int = 137  # Polygon mainnet

    def redacted(self) -> dict[str, str]:
        """Return a log-safe view (no secrets)."""
        return {
            "private_key": "***",
            "api_key": "***" if self.api_key else "",
            "api_secret": "***",
            "api_passphrase": "***",
            "chain_id": str(self.chain_id),
        }


def build_signer(creds: ClobCredentials):  # pragma: no cover - stub for later phases
    """Construct a py-clob-client signer. Stub until order paths land."""
    raise NotImplementedError("CLOB signing implemented in a later Polymarket phase")
