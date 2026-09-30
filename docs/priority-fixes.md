# P0?P2 implementation status

Implemented against the 2026-09-27 assessment. The historical assessment describes the old code; this document describes the replacement.

| Priority | Delivered |
|---|---|
| P0 secrets | Removed .env from Git tracking; ignored local/generated files; provided placeholder template and safe local credential generator. Retired all ZeroMQ credentials and code. |
| P0 transport | Replaced exposed ZeroMQ PUB/SUB with private Kafka plus PostgreSQL raw archive/outbox and transactional ingestion. Production configuration requires authenticated TLS Kafka and certificate-verified PostgreSQL. |
| P0 validation | Bounded envelopes, strict provider validation, decimal precision/range checks, strict timestamp/ID types, durable quarantine, and per-record rejection without concealing infrastructure failures. |
| P0 state correctness | Validation precedes state changes. Inbox, canonical data, persistent sequence state, checkpoint and outgoing event commit together. Invalid input cannot poison the checkpoint. |
| P1 recovery/scaling | Stable source-qualified event IDs, consumer groups, instrument ownership, persistent deduplication/checkpoints, gap/interruption events, bounded replay tool, and outbox retries. |
| P1 time/contracts | Late history preserved; future/skewed messages quarantined; versioned JSON schemas with exact decimal and 64-bit ID wire representations. |
| P1 configuration/lifecycle | Removed obsolete misspelled ZMQ settings and fixed container names; validated settings; bounded cancellation-based cross-platform shutdown; jittered capped retry, clean-EOF retry, idle timeout, and explicit retry limits. |
| P1 operations | JSON logs, health/readiness/metrics, bounded buffering/outbox budgets, real broker/database tests and a repeatable synthetic load probe. |
| P2 reproducibility | Root Python project/dev dependencies; Python 3.12.12 baseline; uv lock and hash-locked runtime export; minimal non-root digest-pinned container images; .dockerignore; CI lint/tests/build/audit/contract checks. |

Verification performed:

- 48 unit tests passed locally; 60 total tests passed inside Python 3.12.12 Docker, including 12 PostgreSQL/Kafka integration tests.
- Transaction rollback, concurrent duplicate delivery, poison-record isolation, restart deduplication, late history, durable gaps, collector ownership, bounded outbox behavior, retry after publication failure, and actual Kafka redelivery after a missing commit were exercised.
- Application and test images built successfully; PostgreSQL and Kafka became healthy; migrations/bootstrap completed.
- A fresh synthetic raw event traversed the running ingestion service into durable canonical storage; its readiness endpoint returned ready=true with both dependencies healthy. Test containers were stopped afterwards, retaining their volumes.
- A real Binance connection delivered archived frames. A measured ~5.2-second exchange/container clock difference caused the intended future-timestamp quarantine; this was not misreported as a healthy canonical stream.
- Runtime dependency audit: no known vulnerabilities reported by pip-audit at execution time.
- Sequential 1,000-event probe: 8.594 seconds, approximately 116.4 events/second; not a production capacity claim.

Remaining deployment/product work:

- Historical Git secret values remain in past commits; credentials used elsewhere must be retired there. No destructive history rewrite was performed.
- Production infrastructure, per-service credentials/ACLs, TLS handshake testing, multi-broker failure drills, backup restore certification, and monitoring deployment require the actual hosting environment.
- Exchange gaps are durably reported, not automatically repaired. Provider history access and completeness validation remain explicit follow-up work.
- PostgreSQL is the initial archive; object storage, retention automation, higher-throughput batched dispatch, and the architecture's larger load envelope remain later capacity work.
- JSON Schema is the implemented language-neutral event contract. Protobuf/gRPC remains the planned C++ compute boundary; no C++ service is necessary for these fixes.

See [pipeline operations](pipeline-operations.md) for commands and limitations.
