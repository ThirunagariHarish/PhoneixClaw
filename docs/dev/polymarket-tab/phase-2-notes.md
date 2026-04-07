# Polymarket Tab — Phase 2 Notes

**Phase:** 2 — PolymarketBroker connector skeleton
**Spec:** `docs/architecture/polymarket-tab.md` §9 Phase 2 (line ~694)
**Status:** Ready for Cortex review.

## What changed

Created the `PolymarketBroker` connector package with the auth round-trip
and Gamma metadata fetch surface required by Phase 2 DoD. No order paths,
no RTDS — those land in Phase 3+.

### New files
- `services/connector-manager/src/brokers/polymarket/__init__.py` —
  package re-exports.
- `services/connector-manager/src/brokers/polymarket/signing.py` —
  `ClobCredentials` dataclass + redaction helper + `build_signer` stub.
  This is the single seam where private-key material crosses into the
  signer; Phase 2 only needs the seam to exist.
- `services/connector-manager/src/brokers/polymarket/gamma_client.py` —
  async `GammaClient` over `httpx.AsyncClient`. Methods: `list_markets`,
  `get_market`, `get_fee_schedule`, `health_check`. Owns its client; closes
  cleanly via `aclose()` / `async with`. Errors normalized to
  `GammaClientError`.
- `services/connector-manager/src/brokers/polymarket/clob_client.py` —
  thin wrapper around `py-clob-client`. The SDK import is guarded with
  try/except so the module loads even when `py-clob-client` is not
  installed in CI. `is_available()` exposes the SDK state; missing-SDK
  callers fall through to metadata-only mode in the adapter. Order paths
  raise `NotImplementedError` (Phase 2 scope boundary).
- `services/connector-manager/src/brokers/polymarket/adapter.py` —
  `PolymarketBroker(BaseBroker)`:
    - `connect()` enforces `JurisdictionAttestationGate` *first*, then
      opens downstream clients. If SDK is missing or no `private_key` is
      configured, the broker stays in metadata-only mode and connects
      anyway (Gamma is unauthenticated and is the F2/F9 data source).
    - `disconnect()` closes both downstream clients.
    - `health_check()` aggregates Gamma + CLOB; reports `ok` only when
      Gamma is reachable. CLOB health is reported separately so a caller
      can distinguish "metadata works, signing offline" from a full
      outage.
    - `get_account()` returns CLOB account summary or a metadata-only
      placeholder.
    - `submit_order` / `get_positions` / `close_position` raise
      `NotImplementedError` (Phase 2 boundary).
    - `list_markets`, `get_market`, `get_fee_schedule` proxy to Gamma so
      the Phase 4 DiscoveryScanner does not need to reach into `_gamma`.
    - Every outbound call wrapped in `shared/broker/circuit_breaker.py`
      `CircuitBreaker(failure_threshold=5, recovery_timeout=30)`.
- `tests/unit/polymarket/test_broker.py` — 20 unit tests covering Gamma
  client (httpx MockTransport), Clob client (SDK-absent path + redaction),
  and PolymarketBroker (jurisdiction gate, metadata-only connect, health
  aggregation, gamma proxy, NotImplementedError surface, missing
  user_id/session guards).

### Modified files
- `services/connector-manager/requirements.txt` — added
  `py-clob-client>=0.17,<1.0` as an optional dependency. The wrapper
  degrades gracefully when this is not installed.

## DoD checklist

- [x] `PolymarketBroker(BaseBroker)` with `connect/disconnect/get_account/health_check`.
- [x] `gamma_client.list_markets()`, `get_market(id)`, `get_fee_schedule()`.
- [x] Jurisdiction gate enforced in `connect()`.
- [x] Circuit breaker reuses `shared/broker/circuit_breaker.py`.
- [x] No plaintext keys in logs — `ClobCredentials.redacted()` is the
      only sanctioned log payload; `clob_client.connect` exception
      messages contain only the exception class name.
- [ ] `health_check` returns `ok` against staging credentials — **not
      verified live** (no staging keys in this environment); unit tests
      assert the `ok`/`degraded` branches via mocked transport.
- [ ] `markets list non-empty` against live Gamma — **not verified
      live**; unit tests assert non-empty payload via mocked transport.

The two unverified bullets require live network reachability that is out
of scope for a unit-test pass. They will be exercised by the Phase 2
integration test hook (`tests/integration/polymarket/test_connect.py`,
skipped without env keys) which is referenced in the spec but is *not*
listed under Phase 2 files — Quill should add it in the test pass.

## Tests

```
PYTHONPATH=. .venv/bin/python -m pytest tests/unit/polymarket/ -q
38 passed in 0.18s
```

Phase-2 only: 20 new tests, all green. Phase-1 tests (18) still green.

## Lint

```
.venv/bin/python -m ruff check services/connector-manager/src/brokers/polymarket/ tests/unit/polymarket/test_broker.py
All checks passed!
```

The repo-wide `make lint` reports 471 pre-existing errors unrelated to
Phase 2; none originate from files in this phase. Ruff auto-organized
the import block in `adapter.py` (third-party `shared.*` ahead of
package-relative imports).

## Deviations from spec

1. **`signing.py` placement.** Spec lists "all of
   `services/connector-manager/src/brokers/polymarket/` except
   `clob_client.py` order paths, plus `signing.py` stub". Implemented
   `signing.py` as a standalone module with `ClobCredentials` +
   `build_signer` stub. `ClobCredentials` is shared between adapter and
   clob_client to keep credential redaction in one place.
2. **Metadata-only fallback.** The spec implies `connect()` should
   succeed against "staging credentials". When `py-clob-client` is not
   installed *or* no `private_key` is configured, the broker logs at
   INFO and proceeds in metadata-only mode (Gamma is the F2/F9 data
   source and is unauthenticated). This keeps the connector usable in
   CI and on dev machines without Polygon keys, and matches the
   architecture's "read-only Gamma does not need staging keys" note in
   §12. If this is wrong, route back to Atlas.
3. **Order/position surface.** Stubbed with `NotImplementedError` rather
   than omitted. Lets later phases land tests against the surface
   without re-shaping the class.
4. **Imports inside the package** are relative (`from .clob_client import
   ...`). The hyphenated `services/connector-manager` directory is
   reachable via the `services/connector_manager` symlink for absolute
   imports from outside the package; relative imports avoid taking a
   stance on which form callers use.

No design changes. No PRD changes.

## Open risks

- Live Gamma reachability is unverified in this environment; covered
  only by mocked tests. Quill should run the Phase 2 integration hook
  on a machine with outbound network.
- `py-clob-client` version pin (`>=0.17,<1.0`) is a guess based on the
  upstream project's current major. If CI install fails, relax the
  upper bound or drop the constraint — the wrapper already tolerates
  the SDK being absent.
- The `_UpstreamClobClient(host, key=..., chain_id=...)` constructor
  signature is based on the current py-clob-client README. If a real
  install reveals a different signature, only `clob_client.connect()`
  needs to change.
