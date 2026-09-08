# ClearSpend ✦

> A calmer, smarter way to see where your money goes.

[![Flask](https://img.shields.io/badge/Flask-3.1-16342d?logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![PostgreSQL](https://img.shields.io/badge/Database-Neon_Postgres-4a2b65?logo=postgresql&logoColor=white)](https://neon.com/)
[![Vercel](https://img.shields.io/badge/Deployed_on-Vercel-111111?logo=vercel&logoColor=white)](https://vercel.com/)

**[Open ClearSpend ↗](https://clear-spend-23anbkx7l-mariam-3e97.vercel.app/)**

ClearSpend is a full-stack personal-finance dashboard built with Flask. Add transactions, set budgets and savings goals, spot spending patterns, and get an AI-powered next step—all in one friendly workspace.

## What you can do

| 💸 Track | 🎯 Plan | ✨ Understand |
| --- | --- | --- |
| Add, edit, search, filter, and delete transactions. | Create monthly or weekly budgets and savings goals. | Get reports, charts, notifications, and Gemini financial insights. |

| 🔐 Stay in control | 🌍 Make it yours | 🛠️ Manage the app |
| --- | --- | --- |
| Email verification, reset password, 2FA, secure sessions, data export, and account deletion. | Light/dark themes, Arabic/English workspace, base currency, and profile photo. | Admin dashboard, feature flags, support tickets, audit trail, and health checks. |

## Tech stack

`Flask` · `PostgreSQL / Neon` · `Vercel Functions` · `Google Gemini` · `Stripe` · `Brevo` · `Sentry`

## Start locally

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python app.py
```

Then visit **http://127.0.0.1:5000**.

## Environment setup

Copy `.env.example` to `.env`; never commit the resulting `.env` file. The app works locally with SQLite by default. For AI, email, payments, and error tracking, add only the services you need.

| Variable | Needed for | Safe local default |
| --- | --- | --- |
| `SECRET_KEY` | Secure sessions | Use a long random value in production |
| `DATABASE_URL` | Neon / PostgreSQL | Leave empty for local SQLite |
| `GEMINI_API_KEY` | AI financial insights | Leave empty to disable AI requests |
| `GEMINI_MODEL` | Gemini model selection | `gemini-3.6-flash` |
| `ADMIN_EMAIL` | Admin access | Your admin login email |
| `MAIL_*` | Verification and email alerts | Keep delivery suppressed while developing |

## Deploy on Vercel + Neon

1. Create a free [Neon](https://neon.com/) PostgreSQL project and copy its pooled connection string.
2. Import this GitHub repository in [Vercel](https://vercel.com/). The included [vercel.json](vercel.json) is ready for Flask.
3. In **Project Settings → Environment Variables**, add these values for **Production**:

   | Name | Value |
   | --- | --- |
   | `SECRET_KEY` | A newly generated long random value |
   | `DATABASE_URL` | Your Neon connection string |
   | `REQUIRE_POSTGRES` | `true` |
   | `FLASK_DEBUG` | `false` |
   | `APP_BASE_URL` | Your primary Production domain (not a one-off deployment URL) |
   | `SESSION_COOKIE_SECURE` | `true` |
   | `TRUST_PROXY_HEADERS` | `true` |
   | `ADMIN_EMAIL` | Your login email address |
   | `GEMINI_API_KEY` | Your Google AI Studio key, if using AI insights |
   | `GEMINI_MODEL` | `gemini-3.6-flash` |

4. Redeploy after changing environment variables. ClearSpend initializes its PostgreSQL tables on first startup.

### Free-demo switches

Use these while you are not ready to send real emails:

```env
REQUIRE_EMAIL_VERIFICATION=false
MAIL_SUPPRESS_SEND=true
```

## Production notes

- Vercel Functions are stateless, so production data belongs in Neon—not `finance_app.db`.
- Profile photos are stored with the user record for the current small-file implementation. For high-volume production use, move them to object storage.
- Stripe, Brevo, Sentry, and Redis rate limiting are optional. Add their keys only after configuring the corresponding service.
- The Vercel Hobby plan has usage limits and is intended for personal, non-commercial projects.

## Test it

```powershell
python -m pytest -q
```

## Keep secrets secret

Never push `.env`, database URLs, API keys, passwords, or webhook secrets. Use [.env.example](.env.example) as the shareable template instead.

---

Built to make money management feel a little less stressful. 🌿
