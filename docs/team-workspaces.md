# Team workspaces

Migration `008_team_memberships.sql` completes the first team onboarding flow. Workspace owners and administrators can create expiring invitation codes, inspect invitations, revoke pending invitations, list members, change roles, and remove members. The dashboard exposes the same operations in its **Team** section.

Invitation codes contain 256 bits of randomness. The API returns the plaintext code only when it is created and stores only its SHA-256 digest. Codes expire after 1–720 hours, are single-use, and can be revoked. Acceptance requires an authenticated account. A repeated acceptance by the same active member is idempotent; a used, expired, or revoked code cannot add another account.

Roles retain the existing authorization model:

| Role | Portfolio and paper writes | Invite members/viewers | Invite or manage admins | Remove owner |
|---|---:|---:|---:|---:|
| owner | yes | yes | yes | no |
| admin | yes | yes | no | no |
| member | yes | no | no | no |
| viewer | no | no | no | no |

Owners cannot be demoted or removed through these endpoints. Administrators cannot change or remove other administrators. Every invitation, acceptance, role change, revocation, and removal writes an audit event in the same database transaction.

## API

| Method | Path | Behavior |
|---|---|---|
| `GET` | `/v1/workspaces/{tenant}/members` | List workspace members |
| `PATCH` | `/v1/workspaces/{tenant}/members/{user}` | Change a non-owner role |
| `DELETE` | `/v1/workspaces/{tenant}/members/{user}` | Remove a permitted member |
| `POST` | `/v1/workspaces/{tenant}/invitations` | Create an invitation and return its one-time code |
| `GET` | `/v1/workspaces/{tenant}/invitations` | List invitation metadata without secrets |
| `DELETE` | `/v1/workspaces/{tenant}/invitations/{id}` | Revoke a pending invitation |
| `POST` | `/v1/invitations/accept` | Accept a code as the authenticated account |

The initial flow intentionally uses a shareable code. Transactional email can deliver that code after an email provider and verified identity-profile policy are chosen. The API does not infer a trusted email address from arbitrary token claims.
