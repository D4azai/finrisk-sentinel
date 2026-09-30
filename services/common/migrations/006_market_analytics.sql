CREATE TABLE saas.market_sessions (
    market text NOT NULL CHECK(market ~ '^[A-Z0-9]{4}$'),
    session_date date NOT NULL,
    is_demo boolean NOT NULL,
    opens_at timestamptz NOT NULL,
    closes_at timestamptz NOT NULL,
    source text NOT NULL,
    PRIMARY KEY(market,session_date,is_demo),
    CHECK(isfinite(opens_at) AND isfinite(closes_at) AND closes_at>opens_at)
);
CREATE TABLE saas.instrument_feeds (
    instrument_id uuid PRIMARY KEY REFERENCES saas.instruments(id),
    source text NOT NULL,
    max_age_seconds integer NOT NULL CHECK(max_age_seconds BETWEEN 60 AND 604800)
);
CREATE TABLE saas.price_bars (
    id uuid PRIMARY KEY,
    instrument_id uuid NOT NULL REFERENCES saas.instruments(id),
    source text NOT NULL,
    session_date date NOT NULL,
    as_of timestamptz NOT NULL CHECK(isfinite(as_of)),
    received_at timestamptz NOT NULL DEFAULT now(),
    open numeric NOT NULL CHECK(open>0 AND open<1e18),
    high numeric NOT NULL CHECK(high>0 AND high<1e18),
    low numeric NOT NULL CHECK(low>0 AND low<1e18),
    close numeric NOT NULL CHECK(close>0 AND close<1e18),
    volume numeric NOT NULL CHECK(volume>=0 AND volume<1e18),
    adjusted boolean NOT NULL,
    is_demo boolean NOT NULL,
    UNIQUE(instrument_id,source,session_date),
    CHECK(low<=open AND low<=close AND high>=open AND high>=close AND high>=low)
);
CREATE INDEX price_history ON saas.price_bars(instrument_id,source,as_of DESC);
CREATE TABLE saas.fx_rates (
    id uuid PRIMARY KEY,
    base_currency text NOT NULL CHECK(base_currency ~ '^[A-Z]{3}$'),
    quote_currency text NOT NULL CHECK(quote_currency ~ '^[A-Z]{3}$'),
    rate numeric NOT NULL CHECK(rate>0 AND rate<1e18),
    as_of timestamptz NOT NULL CHECK(isfinite(as_of)),
    source text NOT NULL,
    is_demo boolean NOT NULL,
    CHECK(base_currency<>quote_currency),
    UNIQUE(base_currency,quote_currency,source,as_of,is_demo)
);
CREATE INDEX latest_fx ON saas.fx_rates(base_currency,quote_currency,is_demo,as_of DESC);
CREATE TABLE saas.market_imports (
    content_sha256 text PRIMARY KEY,
    imported_at timestamptz NOT NULL DEFAULT now(),
    source text NOT NULL,
    bar_count integer NOT NULL
);
DO $$ DECLARE tbl text; BEGIN
    FOREACH tbl IN ARRAY ARRAY['market_sessions','instrument_feeds','price_bars','fx_rates'] LOOP
        EXECUTE format('ALTER TABLE saas.%I ENABLE ROW LEVEL SECURITY',tbl);
        EXECUTE format('ALTER TABLE saas.%I FORCE ROW LEVEL SECURITY',tbl);
        IF tbl='instrument_feeds' THEN
            EXECUTE 'CREATE POLICY read_data ON saas.instrument_feeds FOR SELECT USING (
                EXISTS(SELECT 1 FROM saas.instruments i WHERE i.id=instrument_id))';
        ELSE
            EXECUTE format('CREATE POLICY read_data ON saas.%I FOR SELECT USING (
                saas.current_user_id() IS NOT NULL AND
                (NOT is_demo OR current_setting(''app.allow_demo_market_data'',true)=''true''))',tbl);
        END IF;
        EXECUTE format('GRANT SELECT ON saas.%I TO finrisk_api',tbl);
    END LOOP;
END $$;
CREATE TABLE saas.valuation_snapshots (
    tenant_id uuid NOT NULL,
    portfolio_id uuid NOT NULL,
    id uuid NOT NULL,
    portfolio_version integer NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by uuid NOT NULL REFERENCES saas.users(id),
    payload jsonb NOT NULL,
    PRIMARY KEY(tenant_id,id),
    FOREIGN KEY(tenant_id,portfolio_id) REFERENCES saas.portfolios(tenant_id,id)
);
ALTER TABLE saas.valuation_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE saas.valuation_snapshots FORCE ROW LEVEL SECURITY;
CREATE POLICY read_snapshots ON saas.valuation_snapshots FOR SELECT USING (
    tenant_id=saas.current_tenant_id() AND EXISTS(SELECT 1 FROM saas.memberships m
        WHERE m.tenant_id=valuation_snapshots.tenant_id AND m.user_id=saas.current_user_id())
);
CREATE POLICY insert_snapshots ON saas.valuation_snapshots FOR INSERT WITH CHECK (
    tenant_id=saas.current_tenant_id() AND created_by=saas.current_user_id() AND
    EXISTS(SELECT 1 FROM saas.memberships m WHERE m.tenant_id=valuation_snapshots.tenant_id
        AND m.user_id=saas.current_user_id() AND m.role IN ('owner','admin','member'))
);
GRANT SELECT,INSERT ON saas.valuation_snapshots TO finrisk_api;
