CREATE TABLE saas.paper_accounts (
    tenant_id uuid NOT NULL REFERENCES saas.workspaces(id),
    id uuid NOT NULL,
    currency text NOT NULL CHECK(currency ~ '^[A-Z]{3}$'),
    cash numeric NOT NULL DEFAULT 100000 CHECK(cash>=0 AND cash<1e30),
    created_by uuid NOT NULL REFERENCES saas.users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(tenant_id,id),
    UNIQUE(tenant_id,currency)
);
CREATE TABLE saas.paper_orders (
    tenant_id uuid NOT NULL,
    account_id uuid NOT NULL,
    id uuid NOT NULL,
    client_request_id uuid NOT NULL,
    instrument_id uuid NOT NULL REFERENCES saas.instruments(id),
    price_bar_id uuid NOT NULL REFERENCES saas.price_bars(id),
    side text NOT NULL CHECK(side IN ('buy','sell')),
    quantity numeric NOT NULL CHECK(quantity>0 AND quantity<1e18),
    status text NOT NULL CHECK(status IN ('filled','rejected')),
    price numeric CHECK(price>0 AND price<1e18),
    reason text NOT NULL,
    created_by uuid NOT NULL REFERENCES saas.users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(tenant_id,account_id,id),
    UNIQUE(tenant_id,account_id,client_request_id),
    FOREIGN KEY(tenant_id,account_id) REFERENCES saas.paper_accounts(tenant_id,id),
    CHECK((status='filled' AND price IS NOT NULL) OR status='rejected')
);
DO $$ DECLARE tbl text; BEGIN
    FOREACH tbl IN ARRAY ARRAY['paper_accounts','paper_orders'] LOOP
        EXECUTE format('ALTER TABLE saas.%I ENABLE ROW LEVEL SECURITY',tbl);
        EXECUTE format('ALTER TABLE saas.%I FORCE ROW LEVEL SECURITY',tbl);
        EXECUTE format('CREATE POLICY read_paper ON saas.%I FOR SELECT USING (
            tenant_id=saas.current_tenant_id() AND EXISTS(SELECT 1 FROM saas.memberships m
            WHERE m.tenant_id=%I.tenant_id AND m.user_id=saas.current_user_id()))',tbl,tbl);
        EXECUTE format('CREATE POLICY write_paper ON saas.%I FOR INSERT WITH CHECK (
            tenant_id=saas.current_tenant_id() AND created_by=saas.current_user_id() AND
            current_setting(''app.allow_demo_market_data'',true)=''true'' AND
            EXISTS(SELECT 1 FROM saas.memberships m WHERE m.tenant_id=%I.tenant_id
            AND m.user_id=saas.current_user_id() AND m.role IN (''owner'',''admin'',''member'')))',tbl,tbl);
        EXECUTE format('GRANT SELECT,INSERT ON saas.%I TO finrisk_api',tbl);
    END LOOP;
END $$;
CREATE POLICY update_paper_cash ON saas.paper_accounts FOR UPDATE USING (
    tenant_id=saas.current_tenant_id() AND current_setting('app.allow_demo_market_data',true)='true' AND
    EXISTS(SELECT 1 FROM saas.memberships m WHERE m.tenant_id=paper_accounts.tenant_id
        AND m.user_id=saas.current_user_id() AND m.role IN ('owner','admin','member'))
) WITH CHECK(tenant_id=saas.current_tenant_id());
GRANT UPDATE(cash) ON saas.paper_accounts TO finrisk_api;
