# ClearSpend

ClearSpend is a Flask finance application for tracking transactions, budgets, savings goals, recurring payments, reports, and AI financial insights. It includes account security, email verification, Arabic account UI, a support area, and an administrator control center.

## Main features

- Secure registration, login, reset password, email verification, remember-me, and email two-factor authentication.
- Transactions, budgets, goals, recurring entries, analytics, reports, exports, and currency conversion.
- Light/dark mode and Arabic account interface. Public landing and authentication pages remain English.
- Support tickets, profile photos, notifications, and account data export/deletion.
- Admin roles, account suspension, feature flags, maintenance mode, announcements, audit logs, health checks, and SQLite backups.

## Local development

1. Install Python 3.11 or later.
2. Create and activate a virtual environment.

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

3. Install dependencies.

   ```powershell
   pip install -r requirements.txt
   ```

4. Create the local environment file.

   ```powershell
   Copy-Item .env.example .env
   ```

5. Fill the values you need in `.env`, then start the app.

   ```powershell
   python app.py
   ```

6. Open `http://127.0.0.1:5000`.

## Environment variables

Never commit `.env`. Use [.env.example](.env.example) as the safe template.

Required in production:

| Variable | Production value |
| --- | --- |
| `SECRET_KEY` | A long random secret; Render can generate it. |
| `DATABASE_URL` | Render PostgreSQL internal connection URL. |
| `REQUIRE_POSTGRES` | `true` |
| `APP_BASE_URL` | Your final URL, for example `https://your-app.onrender.com`. |
| `FLASK_DEBUG` | `false` |
| `SESSION_COOKIE_SECURE` | `true` |
| `TRUST_PROXY_HEADERS` | `true` |
| `ADMIN_EMAIL` | The email address of the administrator account. |

For Brevo email delivery, set `REQUIRE_EMAIL_VERIFICATION=true`, `MAIL_SUPPRESS_SEND=false`, and add the SMTP values shown in `.env.example`. `MAIL_DEFAULT_SENDER` must be a sender address verified in Brevo.

Optional integrations: `GEMINI_API_KEY`, Stripe keys, `SENTRY_DSN`, and a Redis `RATELIMIT_STORAGE_URI`.

## Deploy on Render, step by step

1. Rotate any API/SMTP/payment keys that were ever exposed in screenshots, chat, or Git commits.
2. Create a private GitHub repository and push this project. Do not add `.env`, `finance_app.db`, uploads, backups, or virtual environments.
3. In Render, create a **PostgreSQL** database in the same region as the app. Copy its **internal** connection string.
4. In Render, click **New** → **Blueprint**, select the GitHub repository, and let Render read `render.yaml`.
5. After the web service is created, open it and copy its public URL. In **Environment**, set `APP_BASE_URL` to that URL.
6. In the same **Environment** page, add the secret values: `DATABASE_URL`, `GEMINI_API_KEY` (if used), Brevo SMTP values, `ADMIN_EMAIL`, and any Stripe/Sentry/Redis values you use.
7. Confirm these production values: `REQUIRE_POSTGRES=true`, `REQUIRE_EMAIL_VERIFICATION=true`, `MAIL_SUPPRESS_SEND=false`, `FLASK_DEBUG=false`, `SESSION_COOKIE_SECURE=true`, and `TRUST_PROXY_HEADERS=true`.
8. Click **Manual Deploy** → **Deploy latest commit**. Wait for the health check at `/api/health` to pass.
9. Register the account that matches `ADMIN_EMAIL`, verify its email, then log in. It opens the admin control center.
10. Test registration, verification email, login, password reset, an AI request, profile image upload, and one admin action before sharing the site.

Render Blueprint secrets are intentionally declared with `sync: false`; their values belong in Render's Environment dashboard, not `render.yaml`. See Render's [Blueprint reference](https://render.com/docs/blueprint-spec) and [environment-variable guide](https://render.com/docs/configure-environment-variables).

## Tests

```powershell
python -m pytest -q
```

## Backups

For local SQLite development, an administrator can create a backup from the control center or run:

```powershell
python scripts/backup_database.py
```

For production PostgreSQL, configure backups through Render and retain them according to your privacy policy.
