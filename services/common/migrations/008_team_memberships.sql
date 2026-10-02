CREATE TABLE saas.membership_invitations (
    tenant_id uuid NOT NULL REFERENCES saas.workspaces(id),
    id uuid NOT NULL,
    token_sha256 bytea NOT NULL UNIQUE CHECK(octet_length(token_sha256)=32),
    role text NOT NULL CHECK(role IN ('admin','member','viewer')),
    created_by uuid NOT NULL REFERENCES saas.users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    accepted_by uuid REFERENCES saas.users(id),
    accepted_at timestamptz,
    revoked_at timestamptz,
    PRIMARY KEY(tenant_id,id),
    CHECK(expires_at>created_at),
    CHECK((accepted_by IS NULL AND accepted_at IS NULL) OR
          (accepted_by IS NOT NULL AND accepted_at IS NOT NULL))
);
CREATE INDEX membership_invitations_by_tenant
    ON saas.membership_invitations(tenant_id,created_at DESC);

ALTER TABLE saas.membership_invitations ENABLE ROW LEVEL SECURITY;
ALTER TABLE saas.membership_invitations FORCE ROW LEVEL SECURITY;
CREATE POLICY read_invitations ON saas.membership_invitations FOR SELECT USING (
    tenant_id=saas.current_tenant_id() AND EXISTS(
        SELECT 1 FROM saas.memberships m WHERE m.tenant_id=membership_invitations.tenant_id
        AND m.user_id=saas.current_user_id() AND m.role IN ('owner','admin'))
);
CREATE POLICY insert_invitations ON saas.membership_invitations FOR INSERT WITH CHECK (
    tenant_id=saas.current_tenant_id() AND created_by=saas.current_user_id() AND EXISTS(
        SELECT 1 FROM saas.memberships m WHERE m.tenant_id=membership_invitations.tenant_id
        AND m.user_id=saas.current_user_id() AND m.role IN ('owner','admin'))
);
CREATE POLICY update_invitations ON saas.membership_invitations FOR UPDATE USING (
    tenant_id=saas.current_tenant_id() AND EXISTS(
        SELECT 1 FROM saas.memberships m WHERE m.tenant_id=membership_invitations.tenant_id
        AND m.user_id=saas.current_user_id() AND m.role IN ('owner','admin'))
) WITH CHECK (
    tenant_id=saas.current_tenant_id() AND EXISTS(
        SELECT 1 FROM saas.memberships m WHERE m.tenant_id=membership_invitations.tenant_id
        AND m.user_id=saas.current_user_id() AND m.role IN ('owner','admin'))
);

-- Membership mutations cross the normal membership RLS boundary. These narrow functions
-- validate the current authenticated actor and keep authorization in the same transaction.
CREATE FUNCTION saas.accept_membership_invitation(invite_digest bytea)
RETURNS TABLE(status text, invitation_id uuid, accepted_tenant_id uuid, accepted_role text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,saas AS $$
DECLARE
    actor uuid := saas.current_user_id();
    invitation saas.membership_invitations%ROWTYPE;
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

CREATE FUNCTION saas.workspace_members()
RETURNS TABLE(user_id uuid, role text, created_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,saas AS $$
DECLARE tenant uuid := saas.current_tenant_id(); actor uuid := saas.current_user_id();
BEGIN
    IF actor IS NULL OR NOT EXISTS(SELECT 1 FROM saas.memberships m
        WHERE m.tenant_id=tenant AND m.user_id=actor) THEN
        RETURN;
    END IF;
    RETURN QUERY SELECT m.user_id,m.role,m.created_at FROM saas.memberships m
        WHERE m.tenant_id=tenant ORDER BY m.created_at,m.user_id;
END $$;

CREATE FUNCTION saas.set_membership_role(target_user uuid, new_role text) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,saas AS $$
DECLARE
    tenant uuid := saas.current_tenant_id(); actor uuid := saas.current_user_id();
    actor_role text; target_role text;
BEGIN
    SELECT m.role INTO actor_role FROM saas.memberships m
        WHERE m.tenant_id=tenant AND m.user_id=actor;
    SELECT m.role INTO target_role FROM saas.memberships m
        WHERE m.tenant_id=tenant AND m.user_id=target_user FOR UPDATE;
    IF new_role NOT IN ('admin','member','viewer') OR target_role IS NULL OR target_role='owner'
        OR actor=target_user OR actor_role NOT IN ('owner','admin')
        OR (actor_role='admin' AND (target_role='admin' OR new_role='admin')) THEN
        RETURN false;
    END IF;
    UPDATE saas.memberships SET role=new_role
        WHERE tenant_id=tenant AND user_id=target_user;
    RETURN true;
END $$;

CREATE FUNCTION saas.remove_workspace_member(target_user uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,saas AS $$
DECLARE
    tenant uuid := saas.current_tenant_id(); actor uuid := saas.current_user_id();
    actor_role text; target_role text;
BEGIN
    SELECT m.role INTO actor_role FROM saas.memberships m
        WHERE m.tenant_id=tenant AND m.user_id=actor;
    SELECT m.role INTO target_role FROM saas.memberships m
        WHERE m.tenant_id=tenant AND m.user_id=target_user FOR UPDATE;
    IF target_role IS NULL OR target_role='owner' OR actor=target_user
        OR actor_role NOT IN ('owner','admin')
        OR (actor_role='admin' AND target_role='admin') THEN
        RETURN false;
    END IF;
    DELETE FROM saas.memberships WHERE tenant_id=tenant AND user_id=target_user;
    RETURN true;
END $$;

GRANT SELECT,INSERT ON saas.membership_invitations TO finrisk_api;
GRANT UPDATE(revoked_at) ON saas.membership_invitations TO finrisk_api;
GRANT SELECT,UPDATE,DELETE ON saas.memberships TO finrisk_workspace_bootstrap;
GRANT SELECT,UPDATE ON saas.membership_invitations TO finrisk_workspace_bootstrap;
ALTER FUNCTION saas.accept_membership_invitation(bytea) OWNER TO finrisk_workspace_bootstrap;
ALTER FUNCTION saas.workspace_members() OWNER TO finrisk_workspace_bootstrap;
ALTER FUNCTION saas.set_membership_role(uuid,text) OWNER TO finrisk_workspace_bootstrap;
ALTER FUNCTION saas.remove_workspace_member(uuid) OWNER TO finrisk_workspace_bootstrap;
REVOKE ALL ON FUNCTION saas.accept_membership_invitation(bytea) FROM PUBLIC;
REVOKE ALL ON FUNCTION saas.workspace_members() FROM PUBLIC;
REVOKE ALL ON FUNCTION saas.set_membership_role(uuid,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION saas.remove_workspace_member(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION saas.accept_membership_invitation(bytea) TO finrisk_api;
GRANT EXECUTE ON FUNCTION saas.workspace_members() TO finrisk_api;
GRANT EXECUTE ON FUNCTION saas.set_membership_role(uuid,text) TO finrisk_api;
GRANT EXECUTE ON FUNCTION saas.remove_workspace_member(uuid) TO finrisk_api;
