CREATE TABLE saas.portfolio_transaction_imports (
    tenant_id uuid NOT NULL,
    portfolio_id uuid NOT NULL,
    id uuid NOT NULL,
    client_request_id uuid NOT NULL,
    content_sha256 text NOT NULL CHECK(content_sha256 ~ '^[a-f0-9]{64}$'),
    source_filename text CHECK(source_filename IS NULL OR length(source_filename) BETWEEN 1 AND 255),
    status text NOT NULL DEFAULT 'previewed' CHECK(status IN ('previewed','committed')),
    row_count integer NOT NULL CHECK(row_count BETWEEN 1 AND 500),
    valid_count integer NOT NULL CHECK(valid_count BETWEEN 0 AND row_count),
    error_count integer NOT NULL CHECK(error_count=row_count-valid_count),
    created_by uuid NOT NULL REFERENCES saas.users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    committed_at timestamptz,
    PRIMARY KEY(tenant_id,portfolio_id,id),
    UNIQUE(tenant_id,portfolio_id,client_request_id),
    FOREIGN KEY(tenant_id,portfolio_id) REFERENCES saas.portfolios(tenant_id,id),
    CHECK(expires_at>created_at),
    CHECK((status='previewed' AND committed_at IS NULL) OR
          (status='committed' AND committed_at IS NOT NULL))
);
CREATE INDEX portfolio_import_history ON saas.portfolio_transaction_imports
    (tenant_id,portfolio_id,created_at DESC);

CREATE TABLE saas.portfolio_transaction_import_rows (
    tenant_id uuid NOT NULL,
    portfolio_id uuid NOT NULL,
    import_id uuid NOT NULL,
    row_number integer NOT NULL CHECK(row_number BETWEEN 2 AND 501),
    payload jsonb NOT NULL,
    errors jsonb NOT NULL,
    PRIMARY KEY(tenant_id,portfolio_id,import_id,row_number),
    FOREIGN KEY(tenant_id,portfolio_id,import_id)
        REFERENCES saas.portfolio_transaction_imports(tenant_id,portfolio_id,id),
    CHECK(jsonb_typeof(payload)='object' AND jsonb_typeof(errors)='array')
);

ALTER TABLE saas.portfolio_transaction_imports ENABLE ROW LEVEL SECURITY;
ALTER TABLE saas.portfolio_transaction_imports FORCE ROW LEVEL SECURITY;
ALTER TABLE saas.portfolio_transaction_import_rows ENABLE ROW LEVEL SECURITY;
ALTER TABLE saas.portfolio_transaction_import_rows FORCE ROW LEVEL SECURITY;
CREATE POLICY read_portfolio_import ON saas.portfolio_transaction_imports FOR SELECT USING (
    tenant_id=saas.current_tenant_id() AND EXISTS(
        SELECT 1 FROM saas.memberships m WHERE m.tenant_id=portfolio_transaction_imports.tenant_id
        AND m.user_id=saas.current_user_id())
);
CREATE POLICY create_portfolio_import ON saas.portfolio_transaction_imports FOR INSERT WITH CHECK (
    tenant_id=saas.current_tenant_id() AND created_by=saas.current_user_id() AND EXISTS(
        SELECT 1 FROM saas.memberships m WHERE m.tenant_id=portfolio_transaction_imports.tenant_id
        AND m.user_id=saas.current_user_id() AND m.role IN ('owner','admin','member'))
);
CREATE POLICY read_portfolio_import_rows ON saas.portfolio_transaction_import_rows FOR SELECT USING (
    tenant_id=saas.current_tenant_id() AND EXISTS(
        SELECT 1 FROM saas.memberships m WHERE m.tenant_id=portfolio_transaction_import_rows.tenant_id
        AND m.user_id=saas.current_user_id())
);
CREATE POLICY create_portfolio_import_rows ON saas.portfolio_transaction_import_rows
FOR INSERT WITH CHECK (
    tenant_id=saas.current_tenant_id() AND EXISTS(
        SELECT 1 FROM saas.portfolio_transaction_imports i
        WHERE i.tenant_id=portfolio_transaction_import_rows.tenant_id
        AND i.portfolio_id=portfolio_transaction_import_rows.portfolio_id
        AND i.id=portfolio_transaction_import_rows.import_id
        AND i.created_by=saas.current_user_id())
);
CREATE POLICY commit_portfolio_import ON saas.portfolio_transaction_imports FOR UPDATE USING (
    tenant_id=saas.current_tenant_id() AND created_by=saas.current_user_id() AND EXISTS(
        SELECT 1 FROM saas.memberships m WHERE m.tenant_id=portfolio_transaction_imports.tenant_id
        AND m.user_id=saas.current_user_id() AND m.role IN ('owner','admin','member'))
) WITH CHECK(tenant_id=saas.current_tenant_id() AND created_by=saas.current_user_id());

GRANT SELECT,INSERT ON saas.portfolio_transaction_imports,
    saas.portfolio_transaction_import_rows TO finrisk_api;
GRANT UPDATE(status,committed_at) ON saas.portfolio_transaction_imports TO finrisk_api;
