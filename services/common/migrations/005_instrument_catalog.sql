CREATE TABLE saas.instruments (
    id uuid PRIMARY KEY,
    market text NOT NULL CHECK(market ~ '^[A-Z0-9]{4}$'),
    symbol text NOT NULL CHECK(symbol ~ '^[A-Z0-9][A-Z0-9._-]{0,31}$'),
    currency text NOT NULL CHECK(currency ~ '^[A-Z]{3}$'),
    name text NOT NULL CHECK(length(name) BETWEEN 1 AND 160),
    isin text CHECK(isin ~ '^[A-Z]{2}[A-Z0-9]{9}[0-9]$'),
    asset_class text NOT NULL DEFAULT 'equity' CHECK(asset_class='equity'),
    is_demo boolean NOT NULL DEFAULT false,
    active boolean NOT NULL DEFAULT true,
    source text NOT NULL CHECK(length(source) BETWEEN 1 AND 500),
    verified_at timestamptz NOT NULL CHECK(isfinite(verified_at)),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK(is_demo OR isin IS NOT NULL),
    UNIQUE(market,symbol,currency),
    UNIQUE(id,market,symbol,currency,is_demo)
);
CREATE INDEX instruments_by_isin ON saas.instruments(isin);
CREATE INDEX instruments_by_market ON saas.instruments(market,id);
ALTER TABLE saas.instruments ENABLE ROW LEVEL SECURITY;
ALTER TABLE saas.instruments FORCE ROW LEVEL SECURITY;
CREATE POLICY read_reference_data ON saas.instruments FOR SELECT USING (
    saas.current_user_id() IS NOT NULL AND
    (NOT is_demo OR current_setting('app.allow_demo_market_data',true)='true')
);
GRANT SELECT ON saas.instruments TO finrisk_api;

-- Existing history remains unchanged. New API records resolve a trusted listing.
ALTER TABLE saas.portfolio_transactions ADD COLUMN instrument_id uuid;
ALTER TABLE saas.portfolio_transactions ADD COLUMN is_demo boolean NOT NULL DEFAULT false;
ALTER TABLE saas.portfolio_transactions ADD CONSTRAINT transaction_listing_matches
    FOREIGN KEY(instrument_id,market,symbol,currency,is_demo)
    REFERENCES saas.instruments(id,market,symbol,currency,is_demo);
CREATE POLICY require_registered_transaction ON saas.portfolio_transactions
    AS RESTRICTIVE FOR INSERT WITH CHECK (
        instrument_id IS NOT NULL AND
        (NOT is_demo OR current_setting('app.allow_demo_market_data',true)='true')
    );

CREATE TABLE saas.catalog_imports (
    id uuid PRIMARY KEY,
    imported_at timestamptz NOT NULL DEFAULT now(),
    content_sha256 text NOT NULL CHECK(content_sha256 ~ '^[a-f0-9]{64}$'),
    record_count integer NOT NULL CHECK(record_count BETWEEN 1 AND 10000)
);
-- Operator-only provenance: no application privileges and no public write routes.
REVOKE ALL ON saas.catalog_imports FROM PUBLIC;
