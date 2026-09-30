# Pipeline operations

## Security and deployment

Local Compose deliberately has no host-published data or health ports. The data network is internal; only collectors join an outbound network for exchange access. All application containers run as UID 10001 with a read-only root filesystem, dropped capabilities, and no privilege escalation. Local PostgreSQL uses its generated development account; this is not the production role model.

The old ZeroMQ path and its keys have been retired. The local .env was replaced with fresh database credentials and removed from Git tracking. Historical Git commits still contain the former values; they are not valid credentials for this implementation. If those keys were copied into any other deployment, retire them there too. Git history was not rewritten.

Production must set FINRISK_ENVIRONMENT=production, FINRISK_KAFKA_SECURITY_PROTOCOL=SASL_SSL, a SCRAM username/password, and FINRISK_DATABASE_URL with sslmode=verify-full. A custom CA may be supplied via FINRISK_KAFKA_CA_FILE. Do not use the local Compose broker as a production deployment. Mount secrets through the platform secret manager, never a committed environment file. Configure Kafka ACLs for each role/topic/group; use a separate migration principal and narrowly scoped database runtime accounts. Runtime code never runs DDL.

Provision production topics in infrastructure tooling: raw, canonical, quality and quarantine; at least three replicas and min.insync.replicas=2 for the intended fault-tolerant deployment, with producer acks=all. Partition count and retention require capacity planning. The local bootstrap intentionally uses six partitions and one replica and refuses production mode.

Run migrations once before services: python -m services.common.migrate. Migration execution is serialized by a PostgreSQL advisory lock and recorded in schema_migrations. Take a backup before schema changes. Pin/update image digests and locked packages as part of maintenance; a passed Python dependency audit is not an OS-image vulnerability certification.

## Delivery and ownership

Collectors own disjoint instrument sets using PostgreSQL session advisory locks. Raw writes use that same connection, so a lost ownership connection cannot continue writing through an automatically reconnected session. Starting a second collector with overlapping symbols fails. To scale collectors, configure disjoint MARKET_DATA_SYMBOLS sets; scaling identical replicas is intentionally rejected.

Each received frame is committed to raw_frames and a raw outbox row together. The outbox retries Kafka publication. Kafka consumers commit offsets only after a transaction has committed input bytes, canonical or quarantined data, persistent instrument state, a partition checkpoint, and output outbox rows. A rebalance or crash can redeliver; inbox coordinates and canonical IDs deduplicate it. Conflicting payloads with the same source trade ID are quarantined.

Outbox delivery is at least once. A crash after Kafka accepts an event but before PostgreSQL marks it published can repeat that event. Downstream consumers must deduplicate event_id; do not interpret Kafka idempotent-producer support as exactly-once database-to-broker delivery. One advisory-lock-protected dispatcher per topic preserves outbox order across replicas. This is deliberately conservative and should be replaced by measured partitioned/batched dispatch when throughput warrants it.

Raw and clean outboxes have configured pending budgets. When full, input processing waits with the current item unacknowledged. Network buffers are bounded. This does not guarantee receipt from an exchange through an indefinite infrastructure outage: reconnection events explicitly mark recovery as unverified. Local PostgreSQL archives are the initial persistent sink; object-storage archival/retention is the next storage evolution.

## Clock and data quality

Host/container clocks must be synchronized. The default future-source-time tolerance is two seconds relative to recorded receipt. An actual local feed check observed Binance approximately 5.2 seconds ahead of the container; future_source_time records were correctly quarantined. Fix clock synchronization rather than broadening production tolerance to hide clock errors.

Late trades are archived with a late quality flag and cannot replace the current live-price projection. Historical replay is valid; it is not discarded by wall-clock age. Higher invalid IDs never advance sequence state. Valid older missing trades can fill history without moving the checkpoint backward. Sequence gaps and collector start/reconnect intervals generate durable quality events with recovery_status=unverified. No automatic exchange-history backfill or completeness certification is implemented. Risk consumers must consult quality history before treating a time window as complete.

Binary WebSocket frames are archived as base64 rather than lossy text replacement; the normalizer decodes strictly and quarantines invalid data. Oversized WebSocket frames terminate that connection and produce an interruption event; they are not fully retained in memory.

## Recovery and replay

1. Inspect /live, /ready, /metrics, service logs, quality_events, quarantine, and pending outbox age. Logs intentionally omit payloads and connection secrets.
2. Restore PostgreSQL/Kafka connectivity before restarting workers. Restarting a consumer replays uncommitted input automatically.
3. A publish failure leaves the corresponding outbox rows pending. Do not manually delete them to clear an alert.
4. If broker retention expired or an input needs reprocessing, replay an explicitly bounded interval from raw_frames:

```sh
docker compose run --rm --no-deps ingestion python -m scripts.replay --from-time 2026-09-27T12:00:00+00:00 --to-time 2026-09-27T12:01:00+00:00 --limit 10000
```

Replay adds new delivery IDs while preserving canonical IDs. Existing valid trades deduplicate; missing trades can be restored. It is not a model/schema migration mechanism for recomputing already accepted trades. Choose an isolated target dataset for such migrations. Keep a collector/outbox worker running to publish raw replay rows; if overlap would create duplicate collectors, use the existing collector. The tool refuses intervals exceeding the specified limit rather than silently truncating.

5. For upstream data never received, obtain a supported provider history source with the necessary access rights. Ingest it through the same validation contracts and verify the missing interval. Do not clear quality warnings merely because the feed reconnected.
6. Take database backups with point-in-time recovery and test restores. Retention cleanup must not delete pending outbox rows or data needed by the replay window. No automatic destructive archive cleanup is enabled; alert on database disk usage and move historical partitions to object storage before sustained expansion. Local broker retention is seven days or roughly 1 GiB per partition, whichever limit expires data first; raw_frames currently retain received input independently.

On SIGTERM/SIGINT, intake and workers are canceled, open transactions roll back, then clients close within bounded deadlines. Containers allow 45 seconds. Canceling a publish can leave duplicate delivery, which is why stable event IDs are mandatory.

## Monitoring

Internal endpoints:

- /live: process responds and is not shutting down.
- /ready: database and broker checks pass and accepted input was recently observed.
- /metrics: received/processed/published totals, failure counts, pending outbox count/age, and feed age.

Use readiness for routing or operational alarms; use liveness for crash detection. An intentionally quiet instrument or idle consumer replica may be unready without being dead. Do not restart a healthy idle process based only on readiness. Initial alerts: oldest pending outbox >30 seconds; accepted feed age >30 seconds during expected trading; any rising quarantine count; persistent sequence-gap quality events; database disk/pool pressure. Thresholds must be calibrated to instrument activity. Metrics contain no tenant/symbol cardinality labels.

## Reproducible load probe

On a dedicated development/test stack:

```sh
docker compose run --rm --no-deps -e FINRISK_RUN_INTEGRATION=1 ingestion python -m scripts.load_pipeline --events 1000
```

The probe writes synthetic TEST-prefixed instruments and retains their results for inspection. It refuses production settings. A local run processed 1,000 events in 8.594 seconds (~116.4 events/second), including sequential Kafka publication, database processing, and canonical outbox drain. This is neither a saturation test nor the 5,000-event/second target from the design. Test batching, parallel partitions, hot instruments, consumer reassignment, prolonged outages, and storage costs before claiming that target. Never extrapolate user capacity from this number.
