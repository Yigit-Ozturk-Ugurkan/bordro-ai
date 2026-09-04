# Bordro AI frontend

React, TypeScript, Vite, React Router, and Tailwind CSS power the employee
self-service dashboard. All salary, deduction, comparison, and tax values are
rendered from backend responses; no payroll calculations are implemented in
the browser.

## Local development

1. Copy `.env.example` to `.env` if the API is not running at the default URL.
2. From `backend`, start the Windows-safe API with `python -m app`.
3. From `frontend`, run `npm install` and `npm run dev`.
4. Open `http://localhost:5173/login`.

Keep both browser-facing URLs on `localhost`: the Vite app uses
`http://localhost:5173` and calls `http://localhost:8001`. The backend may bind
to `127.0.0.1`; `localhost` can still reach that listener. This avoids mixing
the `localhost` and `127.0.0.1` cookie sites.

Use `npm test` for the frontend suite and `npm run build` for the production
build.

## Authentication storage

Access tokens are held only in module memory by `src/auth/tokenStore.ts` and
are lost on reload. Refresh credentials are host-only, HTTP-only cookies and
are never returned to or stored by browser JavaScript. On startup, the app uses
the cookie refresh endpoint to rotate the session and obtain a new access
token. No token or payroll response data is written to `sessionStorage` or
`localStorage`.

Local HTTP development uses `AUTH_COOKIE_SECURE=false`. Production startup
requires `AUTH_COOKIE_SECURE=true`; the default `SameSite=Lax`, narrow
`/api/v1/auth` path, explicit CORS origins, and server-side Origin validation
protect the cookie endpoints. Deploy frontend and API under same-site HTTPS
hostnames unless the cookie policy is deliberately redesigned.

Login throttling is a bounded per-process MVP guard. It limits repeated failed
attempts for the same source/account without permanent lockout or account
existence disclosure. A multi-worker or multi-instance deployment must replace
it with a shared rate-limit store at the ingress or application layer.
