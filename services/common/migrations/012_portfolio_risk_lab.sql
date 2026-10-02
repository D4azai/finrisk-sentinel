CREATE TABLE saas.portfolio_risk_snapshots (
    tenant_id uuid NOT NULL,
    portfolio_id uuid NOT NULL,
    id uuid NOT NULL,
    portfolio_version integer NOT NULL CHECK(portfolio_version>0),
    method_version text NOT NULL,
    parameters jsonb NOT NULL,
    data_fingerprint text NOT NULL CHECK(data_fingerprint ~ '^[0-9a-f]{64}$'),
    payload jsonb NOT NULL,
    created_by uuid NOT NULL REFERENCES saas.users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(tenant_id,id),
    FOREIGN KEY(tenant_id,portfolio_id) REFERENCES saas.portfolios(tenant_id,id)
);
CREATE INDEX portfolio_risk_snapshots_recent
    ON saas.portfolio_risk_snapshots(tenant_id,portfolio_id,created_at DESC);

ALTER TABLE saas.portfolio_risk_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE saas.portfolio_risk_snapshots FORCE ROW LEVEL SECURITY;
CREATE POLICY read_portfolio_risk_snapshots ON saas.portfolio_risk_snapshots
FOR SELECT USING (
    tenant_id=saas.current_tenant_id() AND EXISTS(
        SELECT 1 FROM saas.memberships m
        WHERE m.tenant_id=portfolio_risk_snapshots.tenant_id
          AND m.user_id=saas.current_user_id()
    )
);
CREATE POLICY insert_portfolio_risk_snapshots ON saas.portfolio_risk_snapshots
FOR INSERT WITH CHECK (
    tenant_id=saas.current_tenant_id() AND created_by=saas.current_user_id() AND EXISTS(
        SELECT 1 FROM saas.memberships m
        WHERE m.tenant_id=portfolio_risk_snapshots.tenant_id
          AND m.user_id=saas.current_user_id()
          AND m.role IN ('owner','admin','member')
    )
);
GRANT SELECT,INSERT ON saas.portfolio_risk_snapshots TO finrisk_api;
