CREATE SCHEMA saas;
REVOKE ALL ON SCHEMA saas FROM PUBLIC;
DO $$ BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='finrisk_api') THEN
        CREATE ROLE finrisk_api NOLOGIN NOSUPERUSER NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='finrisk_workspace_bootstrap') THEN
        CREATE ROLE finrisk_workspace_bootstrap NOLOGIN NOSUPERUSER BYPASSRLS;
    END IF;
END $$;

CREATE TABLE saas.users (
    id uuid PRIMARY KEY,
    issuer text NOT NULL,
    subject text NOT NULL,
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(issuer,subject)
);
CREATE TABLE saas.workspaces (
    id uuid PRIMARY KEY,
    name text NOT NULL CHECK(length(name) BETWEEN 1 AND 100),
    created_by uuid NOT NULL REFERENCES saas.users(id),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE saas.memberships (
    tenant_id uuid NOT NULL REFERENCES saas.workspaces(id),
    user_id uuid NOT NULL REFERENCES saas.users(id),
    role text NOT NULL CHECK(role IN ('owner','admin','member','viewer')),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(tenant_id,user_id)
);
CREATE INDEX membership_by_user ON saas.memberships(user_id,tenant_id);
CREATE TABLE saas.portfolios (
    tenant_id uuid NOT NULL REFERENCES saas.workspaces(id),
    id uuid NOT NULL,
    name text NOT NULL CHECK(length(name) BETWEEN 1 AND 100),
    base_currency text NOT NULL CHECK(base_currency ~ '^[A-Z]{3}$'),
    created_by uuid NOT NULL REFERENCES saas.users(id),
    version integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(tenant_id,id)
);
CREATE TABLE saas.audit_events (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES saas.workspaces(id),
    actor_id uuid NOT NULL REFERENCES saas.users(id),
    action text NOT NULL,
    resource_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE FUNCTION saas.current_user_id() RETURNS uuid LANGUAGE sql STABLE
SET search_path=pg_catalog AS $$ SELECT id FROM saas.users
    WHERE id=nullif(current_setting('app.user_id',true),'')::uuid AND active $$;
CREATE FUNCTION saas.current_tenant_id() RETURNS uuid LANGUAGE sql STABLE
SET search_path=pg_catalog AS $$ SELECT nullif(current_setting('app.tenant_id',true),'')::uuid $$;

ALTER TABLE saas.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE saas.users FORCE ROW LEVEL SECURITY;
CREATE POLICY own_identity ON saas.users USING (
    issuer=current_setting('app.issuer',true) AND subject=current_setting('app.subject',true)
) WITH CHECK (
    issuer=current_setting('app.issuer',true) AND subject=current_setting('app.subject',true)
);
ALTER TABLE saas.memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE saas.memberships FORCE ROW LEVEL SECURITY;
-- A nonrecursive self-membership lookup underpins every other policy.
CREATE POLICY own_membership ON saas.memberships FOR SELECT USING (user_id=saas.current_user_id());
ALTER TABLE saas.workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE saas.workspaces FORCE ROW LEVEL SECURITY;
CREATE POLICY member_workspace ON saas.workspaces FOR SELECT USING (
    EXISTS(SELECT 1 FROM saas.memberships m WHERE m.tenant_id=id AND m.user_id=saas.current_user_id())
);
ALTER TABLE saas.portfolios ENABLE ROW LEVEL SECURITY;
ALTER TABLE saas.portfolios FORCE ROW LEVEL SECURITY;
CREATE POLICY read_portfolios ON saas.portfolios FOR SELECT USING (
    tenant_id=saas.current_tenant_id() AND EXISTS(
        SELECT 1 FROM saas.memberships m WHERE m.tenant_id=portfolios.tenant_id
        AND m.user_id=saas.current_user_id())
);
CREATE POLICY insert_portfolios ON saas.portfolios FOR INSERT WITH CHECK (
    tenant_id=saas.current_tenant_id() AND created_by=saas.current_user_id() AND EXISTS(
        SELECT 1 FROM saas.memberships m WHERE m.tenant_id=portfolios.tenant_id
        AND m.user_id=saas.current_user_id() AND m.role IN ('owner','admin','member'))
);
CREATE POLICY update_portfolios ON saas.portfolios FOR UPDATE USING (
    tenant_id=saas.current_tenant_id() AND EXISTS(
        SELECT 1 FROM saas.memberships m WHERE m.tenant_id=portfolios.tenant_id
        AND m.user_id=saas.current_user_id() AND m.role IN ('owner','admin','member'))
) WITH CHECK (tenant_id=saas.current_tenant_id());
CREATE POLICY delete_portfolios ON saas.portfolios FOR DELETE USING (
    tenant_id=saas.current_tenant_id() AND EXISTS(
        SELECT 1 FROM saas.memberships m WHERE m.tenant_id=portfolios.tenant_id
        AND m.user_id=saas.current_user_id() AND m.role IN ('owner','admin'))
);
ALTER TABLE saas.audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE saas.audit_events FORCE ROW LEVEL SECURITY;
CREATE POLICY audit_insert ON saas.audit_events FOR INSERT WITH CHECK (
    tenant_id=saas.current_tenant_id() AND actor_id=saas.current_user_id() AND EXISTS(
        SELECT 1 FROM saas.memberships m WHERE m.tenant_id=audit_events.tenant_id
        AND m.user_id=saas.current_user_id() AND m.role IN ('owner','admin','member'))
);

-- The ONLY privileged operation is atomic initial workspace+owner creation.
-- No caller-controlled SQL, user ID or role is accepted by the function.
CREATE FUNCTION saas.create_workspace(workspace_name text) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,saas AS $$
DECLARE new_id uuid := gen_random_uuid(); actor uuid := saas.current_user_id();
BEGIN
    IF actor IS NULL OR NOT EXISTS(SELECT 1 FROM saas.users WHERE id=actor AND active
        AND issuer=current_setting('app.issuer',true) AND subject=current_setting('app.subject',true))
    THEN RAISE EXCEPTION 'Access denied' USING ERRCODE='42501'; END IF;
    INSERT INTO saas.workspaces(id,name,created_by) VALUES(new_id,workspace_name,actor);
    INSERT INTO saas.memberships(tenant_id,user_id,role) VALUES(new_id,actor,'owner');
    RETURN new_id;
END $$;
GRANT USAGE ON SCHEMA saas TO finrisk_api,finrisk_workspace_bootstrap;
GRANT SELECT ON saas.users TO finrisk_workspace_bootstrap;
GRANT INSERT ON saas.workspaces,saas.memberships TO finrisk_workspace_bootstrap;
ALTER FUNCTION saas.create_workspace(text) OWNER TO finrisk_workspace_bootstrap;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA saas FROM PUBLIC;
GRANT EXECUTE ON FUNCTION saas.current_user_id(),saas.current_tenant_id() TO finrisk_api,finrisk_workspace_bootstrap;
GRANT EXECUTE ON FUNCTION saas.create_workspace(text) TO finrisk_api;
GRANT SELECT ON saas.users,saas.workspaces,saas.memberships,saas.portfolios TO finrisk_api;
GRANT INSERT(id,issuer,subject) ON saas.users TO finrisk_api;
GRANT INSERT ON saas.portfolios TO finrisk_api;
GRANT UPDATE(name,version,updated_at) ON saas.portfolios TO finrisk_api;
GRANT DELETE ON saas.portfolios TO finrisk_api;
GRANT INSERT ON saas.audit_events TO finrisk_api;
