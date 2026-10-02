from datetime import UTC, datetime, timedelta
from hashlib import sha256
from secrets import token_urlsafe
from typing import Literal
from uuid import UUID, uuid4

from fastapi import Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from services.api.database import audit, transaction
from services.api.models import StrictBody

TeamRole = Literal["admin", "member", "viewer"]


class InvitationCreate(StrictBody):
    role: TeamRole
    expires_in_hours: int = Field(default=72, ge=1, le=720, strict=True)


class InvitationAccept(StrictBody):
    token: str = Field(min_length=32, max_length=256)


class MembershipUpdate(StrictBody):
    role: TeamRole


class MembershipView(BaseModel):
    user_id: UUID
    role: Literal["owner", "admin", "member", "viewer"]
    created_at: datetime


class InvitationView(BaseModel):
    id: UUID
    role: TeamRole
    created_at: datetime
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None
    status: Literal["pending", "accepted", "expired", "revoked"]


class InvitationCreated(InvitationView):
    token: str


class InvitationAccepted(BaseModel):
    workspace_id: UUID
    role: Literal["owner", "admin", "member", "viewer"]


def invitation_status(row, now: datetime) -> str:
    if row["revoked_at"] is not None:
        return "revoked"
    if row["accepted_at"] is not None:
        return "accepted"
    if row["expires_at"] <= now:
        return "expired"
    return "pending"


def register_team(app, authenticated):
    root = "/v1/workspaces/{tenant_id}"

    @app.get(root + "/members", response_model=list[MembershipView])
    async def list_members(tenant_id: UUID, request: Request, identity=Depends(authenticated)):
        async with transaction(request.app.state.pool, identity, tenant_id) as (connection, _, _):
            return [
                dict(row)
                for row in await connection.fetch("SELECT * FROM saas.workspace_members()")
            ]

    @app.patch(root + "/members/{user_id}", response_model=MembershipView)
    async def update_member(
        tenant_id: UUID,
        user_id: UUID,
        body: MembershipUpdate,
        request: Request,
        identity=Depends(authenticated),
    ):
        async with transaction(request.app.state.pool, identity, tenant_id) as (
            connection,
            actor,
            _,
        ):
            if not await connection.fetchval(
                "SELECT saas.set_membership_role($1,$2)", user_id, body.role
            ):
                raise HTTPException(403, "Membership role change is not allowed")
            await audit(connection, tenant_id, actor, "membership.updated", user_id)
            row = await connection.fetchrow(
                "SELECT * FROM saas.workspace_members() WHERE user_id=$1", user_id
            )
            return dict(row)

    @app.delete(root + "/members/{user_id}", status_code=204)
    async def remove_member(
        tenant_id: UUID, user_id: UUID, request: Request, identity=Depends(authenticated)
    ):
        async with transaction(request.app.state.pool, identity, tenant_id) as (
            connection,
            actor,
            _,
        ):
            if not await connection.fetchval("SELECT saas.remove_workspace_member($1)", user_id):
                raise HTTPException(403, "Membership removal is not allowed")
            await audit(connection, tenant_id, actor, "membership.removed", user_id)
        return Response(status_code=204)

    @app.post(root + "/invitations", status_code=201, response_model=InvitationCreated)
    async def create_invitation(
        tenant_id: UUID,
        body: InvitationCreate,
        request: Request,
        identity=Depends(authenticated),
    ):
        token = token_urlsafe(32)
        invitation_id = uuid4()
        expires_at = datetime.now(UTC) + timedelta(hours=body.expires_in_hours)
        async with transaction(request.app.state.pool, identity, tenant_id) as (
            connection,
            actor,
            role,
        ):
            if role not in {"owner", "admin"} or (role == "admin" and body.role == "admin"):
                raise HTTPException(403, "Membership does not allow this invitation")
            row = await connection.fetchrow(
                """INSERT INTO saas.membership_invitations
                   (tenant_id,id,token_sha256,role,created_by,expires_at)
                   VALUES($1,$2,$3,$4,$5,$6)
                   RETURNING id,role,created_at,expires_at,accepted_at,revoked_at""",
                tenant_id,
                invitation_id,
                sha256(token.encode()).digest(),
                body.role,
                actor,
                expires_at,
            )
            await audit(connection, tenant_id, actor, "invitation.created", invitation_id)
            return {**dict(row), "status": "pending", "token": token}

    @app.get(root + "/invitations", response_model=list[InvitationView])
    async def list_invitations(
        tenant_id: UUID,
        request: Request,
        limit: int = Query(50, ge=1, le=100),
        identity=Depends(authenticated),
    ):
        async with transaction(request.app.state.pool, identity, tenant_id) as (
            connection,
            _,
            role,
        ):
            if role not in {"owner", "admin"}:
                raise HTTPException(403, "Membership does not allow invitation access")
            rows = await connection.fetch(
                """SELECT id,role,created_at,expires_at,accepted_at,revoked_at
                   FROM saas.membership_invitations WHERE tenant_id=$1
                   ORDER BY created_at DESC LIMIT $2""",
                tenant_id,
                limit,
            )
            now = datetime.now(UTC)
            return [{**dict(row), "status": invitation_status(row, now)} for row in rows]

    @app.delete(root + "/invitations/{invitation_id}", status_code=204)
    async def revoke_invitation(
        tenant_id: UUID,
        invitation_id: UUID,
        request: Request,
        identity=Depends(authenticated),
    ):
        async with transaction(request.app.state.pool, identity, tenant_id) as (
            connection,
            actor,
            role,
        ):
            if role not in {"owner", "admin"}:
                raise HTTPException(403, "Membership does not allow invitation access")
            revoked = await connection.fetchval(
                """UPDATE saas.membership_invitations SET revoked_at=now()
                   WHERE tenant_id=$1 AND id=$2 AND accepted_at IS NULL AND revoked_at IS NULL
                   RETURNING id""",
                tenant_id,
                invitation_id,
            )
            if revoked is None:
                raise HTTPException(404, "Pending invitation not found")
            await audit(connection, tenant_id, actor, "invitation.revoked", invitation_id)
        return Response(status_code=204)

    @app.post("/v1/invitations/accept", response_model=InvitationAccepted)
    async def accept_invitation(
        body: InvitationAccept, request: Request, identity=Depends(authenticated)
    ):
        async with transaction(request.app.state.pool, identity) as (connection, actor, _):
            result = await connection.fetchrow(
                "SELECT * FROM saas.accept_membership_invitation($1)",
                sha256(body.token.encode()).digest(),
            )
            status = result["status"]
            if status in {"invalid", "revoked"}:
                raise HTTPException(404, "Invitation not found")
            if status in {"expired", "used"}:
                raise HTTPException(409, f"Invitation is {status}")
            if status == "limit_reached":
                raise HTTPException(403, "Workspace seat limit reached")
            tenant_id = result["accepted_tenant_id"]
            await connection.execute("SELECT set_config('app.tenant_id',$1,true)", str(tenant_id))
            if status == "accepted":
                await audit(
                    connection, tenant_id, actor, "invitation.accepted", result["invitation_id"]
                )
            return {"workspace_id": tenant_id, "role": result["accepted_role"]}
