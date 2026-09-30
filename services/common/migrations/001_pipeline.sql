CREATE TABLE IF NOT EXISTS raw_frames (
    event_id uuid PRIMARY KEY,
    received_at timestamptz NOT NULL,
    envelope text NOT NULL
);
CREATE TABLE IF NOT EXISTS inbox (
    topic text NOT NULL, partition_id integer NOT NULL, offset_id bigint NOT NULL,
    payload bytea NOT NULL, processed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(topic, partition_id, offset_id)
);
CREATE TABLE IF NOT EXISTS partition_checkpoints (
    topic text NOT NULL, partition_id integer NOT NULL, offset_id bigint NOT NULL,
    PRIMARY KEY(topic, partition_id)
);
CREATE TABLE IF NOT EXISTS instrument_state (
    instrument_id text PRIMARY KEY, last_sequence bigint NOT NULL
);
CREATE TABLE IF NOT EXISTS trades (
    event_id text PRIMARY KEY, instrument_id text NOT NULL, sequence_id bigint NOT NULL,
    event_at timestamptz NOT NULL, trade jsonb NOT NULL,
    UNIQUE(instrument_id, sequence_id)
);
CREATE INDEX IF NOT EXISTS trades_history ON trades(instrument_id, event_at);
CREATE TABLE IF NOT EXISTS latest_trades (
    instrument_id text PRIMARY KEY, sequence_id bigint NOT NULL,
    event_at timestamptz NOT NULL, trade jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS quarantine (
    event_id text PRIMARY KEY, reason text NOT NULL, payload bytea NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS quality_events (
    event_id text PRIMARY KEY, details jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS outbox (
    id bigserial PRIMARY KEY, event_id text NOT NULL, topic text NOT NULL,
    message_key text NOT NULL, payload bytea NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(), published_at timestamptz,
    UNIQUE(topic, event_id)
);
CREATE INDEX IF NOT EXISTS outbox_pending ON outbox(topic, id) WHERE published_at IS NULL;
