CREATE TABLE saas.plan_versions (
    plan_code text NOT NULL CHECK(plan_code ~ '^[a-z][a-z0-9_]{1,31}$'),
    version smallint NOT NULL CHECK(version>0),
    name text NOT NULL CHECK(length(name) BETWEEN 1 AND 80),
    entitlements jsonb NOT NULL CHECK(jsonb_typeof(entitlements)='object'),
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(plan_code,version)
);

-- This baseline keeps local and early-access workspaces functional. Paid plan limits and
-- prices are inserted only after the billing country and payment provider are selected.
INSERT INTO saas.plan_versions(plan_code,version,name,entitlements) VALUES(
    'free',1,'Free',jsonb_build_object(
        'seats',5,
        'portfolios',10,
        'watchlist_instruments',25,
        'risk_scans_monthly',100,
        'paper_trading',false
    )
);

CREATE TABLE saas.workspace_subscriptions (
    tenant_id uuid PRIMARY KEY REFERENCES saas.workspaces(id) ON DELETE CASCADE,
    plan_code text NOT NULL,
    plan_version smallint NOT NULL,
    status text NOT NULL DEFAULT 'active'
        CHECK(status IN ('trialing','active','grace','past_due','canceled')),
    provider text CHECK(provider IS NULL OR provider ~ '^[a-z][a-z0-9_]{1,31}$'),
    provider_customer_id text,
    provider_subscription_id text,
    current_period_end timestamptz,
    grace_until timestamptz,
    cancel_at_period_end boolean NOT NULL DEFAULT false,
    verified_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY(plan_code,plan_version) REFERENCES saas.plan_versions(plan_code,version),
    CHECK((provider IS NULL AND provider_customer_id IS NULL AND provider_subscription_id IS NULL)
       OR (provider IS NOT NULL AND provider_customer_id IS NOT NULL))
);
CREATE UNIQUE INDEX workspace_subscription_provider_id
    ON saas.workspace_subscriptions(provider,provider_subscription_id)
    WHERE provider_subscription_id IS NOT NULL;

CREATE TABLE saas.billing_webhook_inbox (
    provider text NOT NULL CHECK(provider ~ '^[a-z][a-z0-9_]{1,31}$'),
    event_id text NOT NULL CHECK(length(event_id) BETWEEN 1 AND 255),
    payload_sha256 bytea NOT NULL CHECK(octet_length(payload_sha256)=32),
    payload bytea NOT NULL CHECK(octet_length(payload)<=1048576),
    status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','processed','failed')),
    attempts integer NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 100),
    received_at timestamptz NOT NULL DEFAULT now(),
    processed_at timestamptz,
    last_error text CHECK(last_error IS NULL OR length(last_error)<=500),
    PRIMARY KEY(provider,event_id),
    CHECK((status='processed' AND processed_at IS NOT NULL) OR status<>'processed')
);
CREATE INDEX billing_webhook_pending
    ON saas.billing_webhook_inbox(received_at) WHERE status IN ('pending','failed');

CREATE TABLE saas.billing_audit (
    tenant_id uuid NOT NULL REFERENCES saas.workspaces(id) ON DELETE CASCADE,
    id uuid NOT NULL,
    event_type text NOT NULL CHECK(length(event_type) BETWEEN 1 AND 100),
    plan_code text NOT NULL,
    plan_version smallint NOT NULL,
    status text NOT NULL,
    source text NOT NULL CHECK(length(source) BETWEEN 1 AND 40),
    effective_at timestamptz NOT NULL DEFAULT now(),
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(tenant_id,id),
    FOREIGN KEY(plan_code,plan_version) REFERENCES saas.plan_versions(plan_code,version)
);

INSERT INTO saas.workspace_subscriptions(tenant_id,plan_code,plan_version)
    SELECT id,'free',1 FROM saas.workspaces ON CONFLICT DO NOTHING;

ALTER TABLE saas.workspace_subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE saas.workspace_subscriptions FORCE ROW LEVEL SECURITY;
CREATE POLICY read_own_subscription ON saas.workspace_subscriptions FOR SELECT USING (
    tenant_id=saas.current_tenant_id() AND EXISTS(
        SELECT 1 FROM saas.memberships m WHERE m.tenant_id=workspace_subscriptions.tenant_id
        AND m.user_id=saas.current_user_id())
);

ALTER TABLE saas.billing_audit ENABLE ROW LEVEL SECURITY;
ALTER TABLE saas.billing_audit FORCE ROW LEVEL SECURITY;
CREATE POLICY read_billing_audit ON saas.billing_audit FOR SELECT USING (
    tenant_id=saas.current_tenant_id() AND EXISTS(
        SELECT 1 FROM saas.memberships m WHERE m.tenant_id=billing_audit.tenant_id
        AND m.user_id=saas.current_user_id() AND m.role IN ('owner','admin'))
);

CREATE FUNCTION saas.check_workspace_quota(target_tenant uuid, quota_name text)
RETURNS TABLE(allowed boolean, quota_limit integer, current_usage bigint)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,saas AS $$
DECLARE
    actor uuid := saas.current_user_id();
    limits jsonb;
BEGIN
    IF target_tenant IS DISTINCT FROM saas.current_tenant_id() OR actor IS NULL OR NOT EXISTS(
        SELECT 1 FROM saas.memberships m
        WHERE m.tenant_id=target_tenant AND m.user_id=actor
    ) THEN
        RAISE EXCEPTION 'Access denied' USING ERRCODE='42501';
    END IF;
    SELECT p.entitlements INTO limits FROM saas.workspace_subscriptions s
        JOIN saas.plan_versions p ON (p.plan_code,p.version)=(s.plan_code,s.plan_version)
        WHERE s.tenant_id=target_tenant FOR UPDATE OF s;
    IF limits IS NULL OR NOT limits ? quota_name OR jsonb_typeof(limits->quota_name)<>'number' THEN
        RAISE EXCEPTION 'Unknown workspace quota' USING ERRCODE='22023';
    END IF;
    quota_limit := (limits->>quota_name)::integer;
    CASE quota_name
        WHEN 'seats' THEN
            SELECT count(*) INTO current_usage FROM saas.memberships m
                WHERE m.tenant_id=target_tenant;
        WHEN 'portfolios' THEN
            SELECT count(*) INTO current_usage FROM saas.portfolios p
                WHERE p.tenant_id=target_tenant;
        WHEN 'watchlist_instruments' THEN
            SELECT count(*) INTO current_usage FROM saas.watchlist_items w
                WHERE w.tenant_id=target_tenant;
        WHEN 'risk_scans_monthly' THEN
            SELECT count(*) INTO current_usage FROM saas.risk_scan_runs r
                WHERE r.tenant_id=target_tenant
                AND r.created_at>=date_trunc('month',now());
        ELSE
            RAISE EXCEPTION 'Unsupported workspace quota' USING ERRCODE='22023';
    END CASE;
    allowed := current_usage < quota_limit;
    RETURN NEXT;
END $$;

CREATE OR REPLACE FUNCTION saas.create_workspace(workspace_name text) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,saas AS $$
DECLARE new_id uuid := gen_random_uuid(); actor uuid := saas.current_user_id();
BEGIN
    IF actor IS NULL OR NOT EXISTS(SELECT 1 FROM saas.users WHERE id=actor AND active
        AND issuer=current_setting('app.issuer',true) AND subject=current_setting('app.subject',true))
    THEN RAISE EXCEPTION 'Access denied' USING ERRCODE='42501'; END IF;
    INSERT INTO saas.workspaces(id,name,created_by) VALUES(new_id,workspace_name,actor);
    INSERT INTO saas.memberships(tenant_id,user_id,role) VALUES(new_id,actor,'owner');
    INSERT INTO saas.workspace_subscriptions(tenant_id,plan_code,plan_version)
        VALUES(new_id,'free',1);
    RETURN new_id;
END $$;

CREATE OR REPLACE FUNCTION saas.accept_membership_invitation(invite_digest bytea)
RETURNS TABLE(status text, invitation_id uuid, accepted_tenant_id uuid, accepted_role text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,saas AS $$
DECLARE
    actor uuid := saas.current_user_id();
    invitation saas.membership_invitations%ROWTYPE;
    seat_limit integer;
BEGIN
    IF actor IS NULL THEN
        RETURN QUERY SELECT 'invalid'::text,NULL::uuid,NULL::uuid,NULL::text;
        RETURN;
    END IF;
    SELECT i.* INTO invitation FROM saas.membership_invitations i
        WHERE i.token_sha256=invite_digest FOR UPDATE;
    IF NOT FOUND THEN
        RETURN QUERY SELECT 'invalid'::text,NULL::uuid,NULL::uuid,NULL::text;
    ELSIF invitation.revoked_at IS NOT NULL THEN
        RETURN QUERY SELECT 'revoked'::text,invitation.id,invitation.tenant_id,invitation.role;
    ELSIF invitation.expires_at<=now() THEN
        RETURN QUERY SELECT 'expired'::text,invitation.id,invitation.tenant_id,invitation.role;
    ELSIF invitation.accepted_by IS NOT NULL THEN
        RETURN QUERY SELECT
            CASE WHEN invitation.accepted_by=actor AND EXISTS(
                SELECT 1 FROM saas.memberships m
                WHERE m.tenant_id=invitation.tenant_id AND m.user_id=actor)
                THEN 'already_accepted' ELSE 'used' END,
            invitation.id,invitation.tenant_id,
            COALESCE((SELECT m.role FROM saas.memberships m
                WHERE m.tenant_id=invitation.tenant_id AND m.user_id=actor),invitation.role);
    ELSE
        SELECT (p.entitlements->>'seats')::integer INTO seat_limit
            FROM saas.workspace_subscriptions s JOIN saas.plan_versions p
            ON (p.plan_code,p.version)=(s.plan_code,s.plan_version)
            WHERE s.tenant_id=invitation.tenant_id FOR UPDATE OF s;
        IF seat_limit IS NULL OR (SELECT count(*) FROM saas.memberships m
            WHERE m.tenant_id=invitation.tenant_id)>=seat_limit THEN
            RETURN QUERY SELECT 'limit_reached'::text,invitation.id,
                invitation.tenant_id,invitation.role;
            RETURN;
        END IF;
        INSERT INTO saas.memberships(tenant_id,user_id,role)
            VALUES(invitation.tenant_id,actor,invitation.role)
            ON CONFLICT(tenant_id,user_id) DO NOTHING;
        UPDATE saas.membership_invitations SET accepted_by=actor,accepted_at=now()
            WHERE tenant_id=invitation.tenant_id AND id=invitation.id;
        RETURN QUERY SELECT 'accepted'::text,invitation.id,invitation.tenant_id,
            COALESCE((SELECT m.role FROM saas.memberships m
                WHERE m.tenant_id=invitation.tenant_id AND m.user_id=actor),invitation.role);
    END IF;
END $$;

GRANT SELECT ON saas.plan_versions,saas.workspace_subscriptions,saas.billing_audit TO finrisk_api;
GRANT SELECT,INSERT,UPDATE ON saas.workspace_subscriptions TO finrisk_workspace_bootstrap;
GRANT SELECT ON saas.plan_versions,saas.portfolios,saas.watchlist_items,
    saas.risk_scan_runs TO finrisk_workspace_bootstrap;
ALTER FUNCTION saas.check_workspace_quota(uuid,text) OWNER TO finrisk_workspace_bootstrap;
ALTER FUNCTION saas.create_workspace(text) OWNER TO finrisk_workspace_bootstrap;
ALTER FUNCTION saas.accept_membership_invitation(bytea) OWNER TO finrisk_workspace_bootstrap;
REVOKE ALL ON FUNCTION saas.check_workspace_quota(uuid,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION saas.create_workspace(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION saas.accept_membership_invitation(bytea) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION saas.check_workspace_quota(uuid,text) TO finrisk_api;
GRANT EXECUTE ON FUNCTION saas.create_workspace(text) TO finrisk_api;
GRANT EXECUTE ON FUNCTION saas.accept_membership_invitation(bytea) TO finrisk_api;
