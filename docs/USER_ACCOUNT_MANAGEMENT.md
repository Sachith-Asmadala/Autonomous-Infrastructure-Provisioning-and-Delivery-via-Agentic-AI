# Member account management

Administrators manage accounts from **Users & roles → Members & access**. The
directory includes account totals, role and status filters, name/email search,
member creation, and an Activate or Deactivate action for each member.

The Add member form creates Developer accounts without a role selector. Additional
admin accounts cannot be created through the UI, the admin provisioning API,
or public registration. The initial administrator is bootstrapped on startup
only when no administrator exists. Changing bootstrap configuration does not
create a second administrator. Existing administrators are retained.

## Account status changes

1. Select Activate or Deactivate beside a member.
2. Review the target account, role, and effect. This saves a pending high-risk
   approval request; the account has not changed yet.
3. Select **Approve activation/deactivation** to apply the change, or **Reject
   change** to cancel it. Closing the dialog leaves the request in the approval
   queue. Expired requests cannot execute.

Only administrators can request or decide account changes. Developers can
review their own eligible work, but cannot decide account changes.
An administrator cannot deactivate their own account. At least one active
administrator must remain. Approval execution rechecks the account state and
revision so a stale request cannot overwrite a later change. On PostgreSQL,
account and approval row locks serialize concurrent status changes and decisions.
SQLite decisions acquire a write transaction before checking approval status.

Deactivation blocks login, refresh, authenticated API requests, and new agent
WebSocket actions. It revokes all saved refresh sessions and advances the
account's token version. Reactivation permits a fresh login with the existing
credentials; previously revoked tokens remain invalid. Work already running
when access is suspended is not cancelled retroactively.

Account records and activity history are retained. Status requests, approval
decisions, and completed changes appear in the existing audit log, with requester
and reviewer attribution.

## API and database update

- `POST /api/v1/auth/users/{user_id}/status-requests` accepts
  `{"is_active": false}` or `{"is_active": true}` and returns HTTP 202 with the
  approval ID, target user, and desired status.
- `POST /api/v1/approvals/{approval_id}/decide` uses the existing approval API.
  Account status requests additionally require `users:manage` permission.

Restart the backend after updating the code. Startup adds the non-null integer
`users.token_version` column with a default of zero to existing SQLite or
PostgreSQL databases. The additive update is safe to run again and preserves
existing accounts. Newly issued access and refresh tokens include the account
version. Legacy signed tokens for registered accounts are also checked against
the stored status and version. The application's existing explicit desktop auth
bypass remains a local demo mode; account access enforcement requires auth enabled.

## Validation

`backend/tests/test_user_management.py` covers approval gating, authorization,
session revocation, reactivation, rejection/expiration, stale, repeated, and
concurrent decisions, administrator safeguards, legacy registered-user tokens, WebSocket
authentication, and upgrading an existing SQLite schema. These tests use
isolated temporary and in-memory databases.

## Two-role transition

The supported roles are **Admin** and **Developer**. Public registration and
member creation cannot assign Operator, Viewer, or another Admin. Login needs
only email and password; the server determines access from the saved account.

On the next backend startup, the compatibility migration converts existing
Operator and Viewer accounts to Developer. This gives former Viewers Developer
capabilities and removes former Operators’ shared administrative capabilities.
Account IDs, usernames, activation status, and activity history are preserved.
Access-token versions are incremented and refresh sessions revoked; affected
members must sign in again. Repeated startups do not repeat the migration.
Unknown and retired role claims are rejected rather than receiving default access.

The public website is at `/`, with separate `/login` and `/signup` pages. New
accounts receive Developer access automatically. Existing members return to
their permitted requested page after signing in, or to `/dashboard`.
