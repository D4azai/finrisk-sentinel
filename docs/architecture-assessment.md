# Current architecture assessment

> Historical baseline. The [P0–P2 implementation status](priority-fixes.md) and [operations runbook](pipeline-operations.md) describe the fixes now implemented; the findings below refer to the earlier ZeroMQ prototype.

Reviewed 2026-09-27 from tracked source, service tests, Dockerfiles, and Compose. Scope: code/design review and available local test execution, not a production penetration test or load certification. No application behavior has been changed by this assessment.

## Current system

```mermaid
flowchart LR
    B[Binance trade WebSocket] --> M[market_data Python service]
    M --> Z[ZeroMQ raw PUB/SUB]
    Z --> I[ingestion Python service]
    I --> C[ZeroMQ clean PUB/SUB]
    C --> D[inspect_stream.py]
```

The connector/factory, retry manager, filter pipeline, adapters, and typed canonical model provide useful separation. Existing unit tests cover happy paths and basic rejection/retry behavior. This is a market-data prototype; there is no application API, customer identity, tenant model, durable database, portfolio ledger, risk engine, UI, subscription integration, or CI configuration in the tracked tree.

## Findings ordered by implementation priority

| Priority | Evidence | Impact and required correction |
|---|---|---|
| P0 before shared deployment | `.env` is tracked; `.gitignore` is empty. Environment variable names include both services' secret keys; values were not printed in this review. | Inspect and rotate any real tracked credentials, remove the file from tracking, add ignored local configuration and a placeholder-only example. Removing a file does not remove its history; coordinate any history rewrite separately. |
| P0 before shared deployment | `services/ingestion/publisher/clean_publisher.py` never consumes configured CURVE keys; Compose exposes `5556:5556`. | Clean stream is plaintext and exposed on host interfaces subject to host firewall. Keep it private, implement authenticated transport, and fail startup for incomplete required security configuration. |
| P0 correctness | `consumer/stream_consumer.py` assumes two frames, valid UTF-8/JSON, and a mapping. `binance_adapter.py` directly indexes/converts fields. | Malformed input can terminate ingestion. Validate envelope and provider payload, limit size, quarantine failures, and isolate per-message exceptions without hiding infrastructure failures. |
| P0 correctness | `ingestion/main.py` applies sequence validation before freshness/adaptation; `sequence_check.py` updates state immediately. | A rejected or malformed high-ID event advances state and can suppress subsequent data. Validate first; commit checkpoint/state only with successful durable processing. |
| P0 foundation | Both transports are bare ZeroMQ PUB/SUB, with no persistent sink, acknowledgments, or replay. | Disconnections, startup timing, or slow subscribers can lose ticks. Introduce durable events and idempotent processing before relying on this for portfolio risk. |
| P1 | `SequenceValidationFilter` keys only by symbol and holds state only in memory; gaps merely log. | Restarts lose checkpoints; replicas see duplicate streams rather than sharing work; future exchanges collide. Use provider-qualified identities, partition ownership, persistent checkpoints, and gap recovery/quality status. |
| P1 | `HealthCheckFilter` accepts missing timestamps and future timestamps, rejects old data by wall clock, and performs unchecked arithmetic. | Bad types crash; replay is rejected; skew is hidden. Validate timestamps and distinguish live freshness from historical validity. |
| P1 | `CanonicalTrade` uses `float` and has no version, source/receive timestamps, instrument identity, or finite/positive constraints. | Weak numerical and cross-language contract. Use exact market quantities, a versioned schema, constraints, and provenance; allow documented floating-point analytics separately. |
| P1 | Compose spells `INGESTION_ZMQ_CLEAN_PUB_ENDPOINTd` with an extra `d`. | Override is ignored; `.env` or default masks the error. Correct and test settings precedence. Fixed `container_name` also obstructs Compose replica scaling. |
| P1 | Both `main.py` shutdown handlers call `loop.stop()` under `asyncio.run`, close sockets before task cancellation, and register Unix-style signal callbacks. | Shutdown can interrupt pending work; Windows signal-handler support differs. Use cancellation and `try/finally`, explicit draining/deadlines, and platform-aware signal handling. |
| P1 | `connection_manager.py` handles exceptions but normal exhausted streams immediately restart; reconnect has no jitter; `max_reconnect_attempts` is unused. | Empty/cleanly closed streams can cause rapid retries; replicas can reconnect together. Define normal-close retry policy, capped jitter, feed-idle detection, and deliberate finite/infinite retry configuration. |
| P1 | Raw publisher enables CURVE only when both keys are present, otherwise silently falls back; no client allowlist/authenticator exists. | Partial configuration downgrades security. CURVE encryption alone is not a tenant/client authorization policy; require complete configuration and permitted identities where retained. |
| P1 | No health/readiness endpoints, persistent recovery workflow, metrics, or load/integration tests. Every accepted trade logs at INFO. | Cannot prove healthy processing or diagnose lag economically. Add aggregate metrics, sampled logs, freshness/readiness, and failure tests. |
| P2 | Both Dockerfiles install before copying source, retain compiler tools, run as root, and use unlocked dependencies; runtime image is Python 3.11 while local interpreters differ. | Packaging/build reproducibility and attack-surface concerns. Verify clean builds, install intended packages after copying needed sources, lock dependencies, choose one tested runtime, and use minimal non-root images. Build failure is not asserted without a completed build. |
| P2 | Empty ignore file; generated caches and IDE files are untracked; no declared test extras/root test setup. | Reproducibility and repository hygiene need a root developer workflow, dependency lock, CI, and appropriate ignores. |

P0 denotes prerequisites for trusting or sharing this prototype, not a claim that every item is an externally exploitable critical vulnerability.

## Corrections to the previous README review

- Raw publisher CURVE support already exists, though optional and incomplete end to end. Clean publisher protection remains missing.
- `wss://` connections use the library's default TLS context when no custom context is supplied; omission of an explicit `ssl=` argument is not evidence certificate verification is disabled. [websockets client documentation](https://websockets.readthedocs.io/en/stable/reference/asyncio/client.html).
- ZeroMQ supports communication across machines. Its bare PUB/SUB pattern lacks the durability and recovery required here; the problem is not a single-node restriction. [ZeroMQ PUB/SUB guide](https://zguide.zeromq.org/docs/chapter5/).
- Dictionary growth is bounded by observed instruments in the present fixed subscription deployment; unbounded instrument churn is a future cardinality concern, not a demonstrated memory leak.
- The README's coverage/type percentages are estimates without measurement and should not be treated as baseline metrics. No dependency vulnerability was confirmed by this review.
- Public exchange symbols/trades are not inherently customer secrets; customer positions, credentials, identity data, and future private exchange access require stricter handling.

## Verification

- Existing suite: **13 passed in 2.50 seconds**, using an isolated temporary Python 3.12 environment with pytest, pytest-asyncio, and the declared runtime dependency families. Command: `python -B -m pytest -q -p no:cacheprovider`. This is not the Docker Python 3.11 environment or a locked dependency reproduction.
- `git diff --check` passed for tracked changes during review.
- Docker CLI exists but the Docker Desktop Linux engine pipe was unavailable; container builds and runtime integration were not executed.
- Static findings reference actual source paths. Production throughput, gap recovery, tenant isolation, and billing reliability cannot be certified by the existing unit suite. Required acceptance gates and the target architecture are in [architecture.md](architecture.md).
