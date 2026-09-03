# Authentication and authorization baseline

The API uses Argon2id password hashes through `pwdlib`; passwords are never
stored reversibly. Access and refresh tokens are HS256 JWTs signed with the
configured `AUTH_SECRET_KEY`. Tokens contain only the user ID, organization
ID, token type, issued/expiry timestamps, and a unique token ID. The decoder
uses an explicit algorithm allowlist and requires every claim.

Roles are deliberately not copied into tokens. Every authenticated request
loads the active user, active organization, current roles, and optional
employee link from the database. This permits immediate access revocation by
deactivating a user or changing their roles. A token whose organization claim
no longer matches the database user is rejected.

Employee self-service endpoints derive the employee ID from the authenticated
user. Employee-ID endpoints first load the target employee and apply the
central payroll policy. Employees may read only their linked employee record;
HR admins, payroll admins, and auditors may read only employees in their own
organization. System administrators receive no implicit payroll access.
Cross-organization requests consistently return `403 Forbidden`; unknown
employee IDs return `404 Not Found`.

Login accepts email and password. Because the current schema makes email
unique only inside an organization, an email found in multiple organizations
is rejected as ambiguous with the same generic `401` used for bad credentials.

Refresh is stateless and issues a new unique refresh token on use; the prior
token remains valid until expiry. Deactivation and secret rotation revoke
tokens globally, but per-token revocation and reuse detection require a future
persisted session/token model.

## Required follow-up security controls

Before internet-facing production deployment, add distributed rate limiting
and progressive throttling for login failures, with security events for login
success/failure and payroll views. Do not log passwords, tokens, or payroll
payloads.
