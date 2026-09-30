CREATE TABLE saas.portfolio_transactions (
    tenant_id uuid NOT NULL,
    portfolio_id uuid NOT NULL,
    id uuid NOT NULL,
    client_request_id uuid NOT NULL,
    market text NOT NULL CHECK(market ~ '^[A-Z0-9]{4}$'),
    symbol text NOT NULL CHECK(symbol ~ '^[A-Z0-9][A-Z0-9._-]{0,31}$'),
    currency text NOT NULL CHECK(currency ~ '^[A-Z]{3}$'),
    side text NOT NULL CHECK(side IN ('buy','sell')),
    quantity numeric NOT NULL CHECK(quantity > 0 AND quantity < 1e18 AND scale(quantity)<=12),
    price numeric NOT NULL CHECK(price > 0 AND price < 1e18 AND scale(price)<=12),
    fees numeric NOT NULL CHECK(fees >= 0 AND fees < 1e18 AND scale(fees)<=12),
    executed_at timestamptz NOT NULL CHECK(isfinite(executed_at)),
    created_by uuid NOT NULL REFERENCES saas.users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(tenant_id,portfolio_id,id),
    UNIQUE(tenant_id,portfolio_id,client_request_id),
    FOREIGN KEY(tenant_id,portfolio_id) REFERENCES saas.portfolios(tenant_id,id)
);
CREATE INDEX transactions_by_instrument ON saas.portfolio_transactions
    (tenant_id,portfolio_id,market,symbol,executed_at);
ALTER TABLE saas.portfolio_transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE saas.portfolio_transactions FORCE ROW LEVEL SECURITY;
CREATE POLICY read_transactions ON saas.portfolio_transactions FOR SELECT USING (
    tenant_id=saas.current_tenant_id() AND EXISTS(
        SELECT 1 FROM saas.memberships m WHERE m.tenant_id=portfolio_transactions.tenant_id
        AND m.user_id=saas.current_user_id())
);
CREATE POLICY insert_transactions ON saas.portfolio_transactions FOR INSERT WITH CHECK (
    tenant_id=saas.current_tenant_id() AND created_by=saas.current_user_id() AND EXISTS(
        SELECT 1 FROM saas.memberships m WHERE m.tenant_id=portfolio_transactions.tenant_id
        AND m.user_id=saas.current_user_id() AND m.role IN ('owner','admin','member'))
);
-- Financial history is append-only and prevents deleting its parent portfolio.
GRANT SELECT,INSERT ON saas.portfolio_transactions TO finrisk_api;
