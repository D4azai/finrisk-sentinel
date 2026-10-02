CREATE TABLE saas.watchlist_items (
    tenant_id uuid NOT NULL REFERENCES saas.workspaces(id),
    instrument_id uuid NOT NULL REFERENCES saas.instruments(id),
    created_by uuid NOT NULL REFERENCES saas.users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(tenant_id,instrument_id)
);

CREATE TABLE saas.alert_rules (
    tenant_id uuid NOT NULL,
    id uuid NOT NULL,
    instrument_id uuid NOT NULL,
    kind text NOT NULL DEFAULT 'daily_anomaly' CHECK(kind='daily_anomaly'),
    enabled boolean NOT NULL DEFAULT true,
    created_by uuid NOT NULL REFERENCES saas.users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(tenant_id,id),
    UNIQUE(tenant_id,instrument_id,kind),
    FOREIGN KEY(tenant_id,instrument_id)
        REFERENCES saas.watchlist_items(tenant_id,instrument_id) ON DELETE CASCADE
);

CREATE TABLE saas.risk_scan_runs (
    tenant_id uuid NOT NULL REFERENCES saas.workspaces(id),
    id uuid NOT NULL,
    client_request_id uuid NOT NULL,
    status text NOT NULL CHECK(status IN ('running','succeeded')),
    evaluated_count integer NOT NULL DEFAULT 0 CHECK(evaluated_count BETWEEN 0 AND 100),
    elevated_count integer NOT NULL DEFAULT 0 CHECK(elevated_count BETWEEN 0 AND evaluated_count),
    new_alert_count integer NOT NULL DEFAULT 0 CHECK(new_alert_count BETWEEN 0 AND elevated_count),
    result jsonb,
    requested_by uuid NOT NULL REFERENCES saas.users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    PRIMARY KEY(tenant_id,id),
    UNIQUE(tenant_id,client_request_id),
    CHECK((status='running' AND completed_at IS NULL AND result IS NULL) OR
          (status='succeeded' AND completed_at IS NOT NULL AND result IS NOT NULL))
);
CREATE INDEX risk_scan_history ON saas.risk_scan_runs(tenant_id,created_at DESC);

CREATE TABLE saas.risk_alerts (
    tenant_id uuid NOT NULL REFERENCES saas.workspaces(id),
    id uuid NOT NULL,
    rule_id uuid NOT NULL,
    instrument_id uuid NOT NULL REFERENCES saas.instruments(id),
    run_id uuid NOT NULL,
    dedupe_key text NOT NULL CHECK(dedupe_key ~ '^[a-f0-9]{64}$'),
    status text NOT NULL DEFAULT 'open' CHECK(status IN ('open','acknowledged')),
    severity text NOT NULL CHECK(severity='elevated'),
    title text NOT NULL CHECK(length(title) BETWEEN 1 AND 200),
    evidence jsonb NOT NULL CHECK(jsonb_typeof(evidence)='object'),
    created_by uuid NOT NULL REFERENCES saas.users(id),
    triggered_at timestamptz NOT NULL DEFAULT now(),
    acknowledged_by uuid REFERENCES saas.users(id),
    acknowledged_at timestamptz,
    PRIMARY KEY(tenant_id,id),
    UNIQUE(tenant_id,dedupe_key),
    FOREIGN KEY(tenant_id,run_id) REFERENCES saas.risk_scan_runs(tenant_id,id),
    CHECK((status='open' AND acknowledged_by IS NULL AND acknowledged_at IS NULL) OR
          (status='acknowledged' AND acknowledged_by IS NOT NULL AND acknowledged_at IS NOT NULL))
);
CREATE INDEX open_risk_alerts ON saas.risk_alerts(tenant_id,triggered_at DESC)
    WHERE status='open';

DO $$ DECLARE tbl text; BEGIN
    FOREACH tbl IN ARRAY ARRAY['watchlist_items','alert_rules','risk_scan_runs','risk_alerts'] LOOP
        EXECUTE format('ALTER TABLE saas.%I ENABLE ROW LEVEL SECURITY',tbl);
        EXECUTE format('ALTER TABLE saas.%I FORCE ROW LEVEL SECURITY',tbl);
        EXECUTE format('CREATE POLICY read_risk_data ON saas.%I FOR SELECT USING (
            tenant_id=saas.current_tenant_id() AND EXISTS(
                SELECT 1 FROM saas.memberships m WHERE m.tenant_id=%I.tenant_id
                AND m.user_id=saas.current_user_id()))',tbl,tbl);
    END LOOP;
END $$;

CREATE POLICY create_watchlist_item ON saas.watchlist_items FOR INSERT WITH CHECK (
    tenant_id=saas.current_tenant_id() AND created_by=saas.current_user_id() AND EXISTS(
        SELECT 1 FROM saas.memberships m WHERE m.tenant_id=watchlist_items.tenant_id
        AND m.user_id=saas.current_user_id() AND m.role IN ('owner','admin','member'))
);
CREATE POLICY delete_watchlist_item ON saas.watchlist_items FOR DELETE USING (
    tenant_id=saas.current_tenant_id() AND EXISTS(
        SELECT 1 FROM saas.memberships m WHERE m.tenant_id=watchlist_items.tenant_id
        AND m.user_id=saas.current_user_id() AND m.role IN ('owner','admin','member'))
);
CREATE POLICY create_alert_rule ON saas.alert_rules FOR INSERT WITH CHECK (
    tenant_id=saas.current_tenant_id() AND created_by=saas.current_user_id() AND EXISTS(
        SELECT 1 FROM saas.memberships m WHERE m.tenant_id=alert_rules.tenant_id
        AND m.user_id=saas.current_user_id() AND m.role IN ('owner','admin','member'))
);
CREATE POLICY update_alert_rule ON saas.alert_rules FOR UPDATE USING (
    tenant_id=saas.current_tenant_id() AND EXISTS(
        SELECT 1 FROM saas.memberships m WHERE m.tenant_id=alert_rules.tenant_id
        AND m.user_id=saas.current_user_id() AND m.role IN ('owner','admin','member'))
) WITH CHECK(tenant_id=saas.current_tenant_id());
CREATE POLICY create_risk_scan ON saas.risk_scan_runs FOR INSERT WITH CHECK (
    tenant_id=saas.current_tenant_id() AND requested_by=saas.current_user_id() AND EXISTS(
        SELECT 1 FROM saas.memberships m WHERE m.tenant_id=risk_scan_runs.tenant_id
        AND m.user_id=saas.current_user_id() AND m.role IN ('owner','admin','member'))
);
CREATE POLICY update_risk_scan ON saas.risk_scan_runs FOR UPDATE USING (
    tenant_id=saas.current_tenant_id() AND requested_by=saas.current_user_id()
) WITH CHECK(tenant_id=saas.current_tenant_id() AND requested_by=saas.current_user_id());
CREATE POLICY create_risk_alert ON saas.risk_alerts FOR INSERT WITH CHECK (
    tenant_id=saas.current_tenant_id() AND created_by=saas.current_user_id() AND EXISTS(
        SELECT 1 FROM saas.memberships m WHERE m.tenant_id=risk_alerts.tenant_id
        AND m.user_id=saas.current_user_id() AND m.role IN ('owner','admin','member'))
);
CREATE POLICY acknowledge_risk_alert ON saas.risk_alerts FOR UPDATE USING (
    tenant_id=saas.current_tenant_id() AND EXISTS(
        SELECT 1 FROM saas.memberships m WHERE m.tenant_id=risk_alerts.tenant_id
        AND m.user_id=saas.current_user_id() AND m.role IN ('owner','admin','member'))
) WITH CHECK(tenant_id=saas.current_tenant_id());

GRANT SELECT,INSERT,DELETE ON saas.watchlist_items TO finrisk_api;
GRANT SELECT,INSERT ON saas.alert_rules TO finrisk_api;
GRANT UPDATE(enabled) ON saas.alert_rules TO finrisk_api;
GRANT SELECT,INSERT ON saas.risk_scan_runs TO finrisk_api;
GRANT UPDATE(status,evaluated_count,elevated_count,new_alert_count,result,completed_at)
    ON saas.risk_scan_runs TO finrisk_api;
GRANT SELECT,INSERT ON saas.risk_alerts TO finrisk_api;
GRANT UPDATE(status,acknowledged_by,acknowledged_at) ON saas.risk_alerts TO finrisk_api;
