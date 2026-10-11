# Stack Up

Stack Up is a personal finance application for uploading Indian bank statement PDFs, reviewing categorized transactions, exploring cash flow and spending analytics, and asking an AI assistant questions about saved transactions. User accounts, statement history, parsed transactions, and original uploaded PDFs are private to each account.

## Project layout

- `frontend/`: React and Vite static web application.
- `backend/`: FastAPI routes for authentication, statement uploads, analysis, and AI queries.
- `database/`: PostgreSQL for production and SQLite for local development, selected by `DATABASE_URL` and `DB_PATH`.
- `services/`: PDF parsing, transaction categorization, financial analysis, OTP delivery, and AI assistance.

## Run locally

1. Install Python packages: `pip install -r requirements.txt`.
2. Install frontend packages: `cd frontend` then `npm ci`.
3. From the project root, start FastAPI with `uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000`.
4. In another terminal, run `cd frontend` then `npm run dev`.
5. Open the Vite URL, normally `http://localhost:5173`. Vite proxies `/api` to the local FastAPI service during development.

Local development uses `stack_up.db` unless `DB_PATH` is set. Keep `.env` private; it is ignored by Git.

## Deploy on Render

Deploy the frontend, API, and database as separate Render services. Set both services to deploy the repository's `main` branch.

### 1. Create PostgreSQL

In Render, create a PostgreSQL database in the same region as the backend. Copy its **Internal Database URL** into the backend service's `DATABASE_URL` environment variable. The application creates or updates its tables on backend startup; it does not drop tables.

Use a database plan with the data retention and backups appropriate for your users. Render's free PostgreSQL databases expire after 30 days, so they are for evaluation rather than long-term production data. See [Render's free service limits](https://render.com/docs/free).

Existing local `stack_up.db` data is not automatically copied into the new PostgreSQL database. The database schema is initialized automatically, but importing old accounts or statements requires a separate data migration.

### 2. Create the FastAPI web service

Connect the GitHub repository as a **Web Service** with:

| Setting | Value |
| --- | --- |
| Root Directory | `.` (repository root) |
| Runtime | Python 3 |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `uvicorn backend.main:app --host 0.0.0.0 --port $PORT` |

Add these environment variables to the backend service:

| Variable | Value |
| --- | --- |
| `APP_ENV` | `production` |
| `DATABASE_URL` | Internal Database URL from the Render PostgreSQL service |
| `FRONTEND_URL` | Exact public frontend origin, such as `https://stack-up.onrender.com` (no trailing slash). Multiple allowed origins may be comma-separated. |
| `COOKIE_SECURE` | `true` |
| `COOKIE_SAMESITE` | `none` |
| `GROQ_API_KEY` | Secret API key for real AI categorization and assistant responses |

Configure the OTP delivery variables needed by your providers:

- Email through Resend HTTPS: `RESEND_API_KEY`. For initial testing without a domain, set `RESEND_FROM_EMAIL=onboarding@resend.dev` and `RESEND_TEST_RECIPIENT` to the email registered with your Resend account. The test sender is restricted in this application to that one recipient.
- For production email after verifying a domain with Resend, set `RESEND_FROM_EMAIL` to a sender on that verified domain. The test-recipient restriction applies only to `onboarding@resend.dev`.
- SMS through Twilio: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, and `TWILIO_PHONE_NUMBER`.

Email OTPs use Resend's HTTPS API; the backend does not fall back to SMTP. SMS OTPs continue to use Twilio.

WhatsApp integration is optional. If used, configure `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN`, and `WHATSAPP_APP_SECRET`.

Render supplies `PORT` at runtime; do not hardcode a production port. The `/health` route can be used as a health check.

### 3. Create the frontend static site

Connect the same repository as a **Static Site** with:

| Setting | Value |
| --- | --- |
| Root Directory | `frontend` |
| Build Command | `npm ci && npm run build` |
| Publish Directory | `dist` |

Add this build-time environment variable to the frontend site:

| Variable | Value |
| --- | --- |
| `VITE_API_BASE_URL` | Public URL of the FastAPI Render service, for example `https://stack-up-api.onrender.com` (no trailing slash or `/api`) |

Vite embeds `VITE_API_BASE_URL` in the static JavaScript at build time. Rebuild the static site after changing it. It must point to the backend service, not the frontend site.

### 4. Match the frontend and backend URLs

Set the backend's `FRONTEND_URL` to the exact origin shown for the deployed static site. Set the frontend's `VITE_API_BASE_URL` to the backend's public URL. These URLs are different: the frontend calls FastAPI directly, and the Vite `/api` proxy is only used for local development.

With these production settings, authentication cookies use `Secure` and `SameSite=None` so credentialed requests can reach the separate HTTPS frontend and API origins. CORS allows only the origin or origins listed in `FRONTEND_URL`.

## Environment variables and secrets

Set production variables in each Render service's Environment page. Never add API keys, SMTP passwords, Twilio tokens, database URLs, or `.env` contents to frontend variables or source control. Variables prefixed with `VITE_` are public because they are included in browser code; use `VITE_API_BASE_URL` only for the public backend URL.

If `DATABASE_URL` is unset outside production, the backend uses SQLite at `DB_PATH` or `stack_up.db`. In production (`APP_ENV=production`), startup requires `DATABASE_URL` and `FRONTEND_URL` rather than silently using ephemeral local SQLite storage.

## Tests and build

Run the frontend production build from `frontend/` with `npm run build`. Python tests and parsing utilities are in `tests/`, `test_parser.py`, and `full_test.py`; the standalone PDF scripts require a local `bank_statement.pdf` fixture.
