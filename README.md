# RK Fashion Operations Portal

Independent internal portal for linesheets, purchase orders, production, inventory, dispatch, and consignment operations. It does not connect to or modify the public RK Fashion website.

## Local setup

1. Copy `.env.example` to `.env` and set a strong `JWT_SECRET` and MongoDB URI.
2. Backend: `cd backend`, create a virtual environment, run `pip install -r requirements.txt`, then `python run.py`.
3. Frontend: `cd frontend`, run `npm install`, then `npm run dev`.
4. Open http://localhost:3000. The API health endpoint is http://localhost:5000/api/health.

Create the first administrator with `python -m app.cli create-admin --email admin@example.com` from `backend`. There are no seeded operational figures or sample orders.

## Architecture

- `backend/app`: Flask application factory, MongoDB repositories, auth/RBAC, domain services, and versioned REST routes.
- `frontend/app`: Next.js App Router pages; `components` contains reusable navigation, tables, forms, and dashboard views.
- MongoDB collections and indexes are created at startup. All quantities are held in integer base units and money in decimal strings.
- Stock and production changes are append-only transactions guarded by idempotency keys and optimistic revision checks.

See [docs/architecture.md](docs/architecture.md) for collections, workflow invariants, and API coverage.

## Zoho WorkDrive

WorkDrive synchronization is optional. Configure the `ZOHO_*` variables shown in `.env.example` with a server-side OAuth refresh token and a WorkDrive root folder ID. Credentials and access tokens are never returned to the frontend.

For OAuth connection, configure `ZOHO_REDIRECT_URI` (or `Zoho_Authorized_Redirect_URI`) to `http://localhost:5006/api/workdrive/callback`, add that exact URL in the Zoho client, and generate a Fernet key for `ZOHO_TOKEN_ENCRYPTION_KEY`. The Admin clicks **Connect Zoho WorkDrive** in `/workspace/settings`; the callback exchanges the code, encrypts the refresh token in MongoDB, refreshes an access token server-side, and verifies the configured root folder before reporting Connected.

Use `GET /api/workdrive/status` to confirm configuration. Individual retained documents can be synchronized with `POST /api/documents/<document-id>/sync-workdrive`. Failed uploads remain stored locally with a `failed` status and can be retried explicitly. A `synced` document with an existing WorkDrive file ID is not uploaded twice.

WorkDrive has not been live-verified unless valid account credentials and a real WorkDrive folder are supplied. Required OAuth scopes depend on the operations enabled for the Zoho account; grant the official WorkDrive file and folder read/write scopes documented for that account rather than broad unrelated scopes.
