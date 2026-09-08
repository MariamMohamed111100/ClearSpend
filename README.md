# ClearSpend

ClearSpend is a Flask financial-management application with account security, budgets, transactions, goals, reports, AI insights, support tickets, and an administrator control center.

## Run locally

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python app.py
```

Open `http://127.0.0.1:5000`.

## Deploy free on Vercel

Vercel hosts the Flask application. A managed PostgreSQL database is required because Vercel Functions do not keep local files between invocations.

### 1. Create a Neon database

1. Create a free Neon account and create a new PostgreSQL project.
2. Copy its connection string. It begins with `postgresql://`.
3. Do not place this connection string in GitHub or `.env.example`.

### 2. Import the repository into Vercel

1. Create a Vercel account and sign in with GitHub.
2. Click **Add New** then **Project**.
3. Import `MariamMohamed111100/ClearSpend`.
4. Keep the framework preset as auto-detected and click **Deploy**.

`app.py` exports the Flask app directly. [vercel.json](vercel.json) includes the templates in the Python function bundle.

### 3. Add Vercel environment variables

Open **Project Settings > Environment Variables** and add these values for **Production**:

| Name | Value |
| --- | --- |
| `SECRET_KEY` | A long new random value. |
| `DATABASE_URL` | The Neon PostgreSQL connection string. |
| `REQUIRE_POSTGRES` | `true` |
| `FLASK_DEBUG` | `false` |
| `APP_BASE_URL` | Your Vercel URL, for example `https://clearspend.vercel.app`. |
| `SESSION_COOKIE_SECURE` | `true` |
| `TRUST_PROXY_HEADERS` | `true` |
| `ADMIN_EMAIL` | Your own login email address. |
| `GEMINI_API_KEY` | Optional; needed for AI insights. |
| `GEMINI_MODEL` | `gemini-3.6-flash` |

For a free demo, also add:

| Name | Value |
| --- | --- |
| `REQUIRE_EMAIL_VERIFICATION` | `false` |
| `MAIL_SUPPRESS_SEND` | `true` |

After adding variables, go to **Deployments** and choose **Redeploy**. On first startup, ClearSpend creates its PostgreSQL tables automatically.

### Vercel demo limitations

- Do not use `finance_app.db` in production. Neon stores the data instead.
- Uploaded profile images are disabled on Vercel until cloud object storage is connected; local uploads are not durable in serverless hosting.
- Stripe billing, Brevo email delivery, Sentry, and Redis rate limiting are optional integrations. Add their keys only when those services are configured.
- Vercel Hobby is for personal/non-commercial projects and has usage limits.

## Secrets

Never commit `.env`, database URLs, SMTP passwords, Stripe keys, or Gemini keys. Use [.env.example](.env.example) only as a safe local template.

## Tests

```powershell
python -m pytest -q
```
