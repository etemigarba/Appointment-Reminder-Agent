# Appointment Reminder Agent

A multi-tenant SaaS agent for small businesses: connects to Google Calendar, sends
appointment reminders via SMS / Email / WhatsApp, and holds AI-powered conversations
with customers to confirm, cancel, or reschedule appointments. Owners get a dashboard
with an approval queue so nothing changes without their sign-off (unless auto mode is on).

See [`backend/README.md`](backend/README.md) for setup, environment variables,
and ops details.

## Architecture

```
Google Calendar ──sync──▶ PostgreSQL (appointments)
                              │
                    ┌─────────▼─────────┐
                    │  Reminder Worker   │  APScheduler: T-24h / T-2h jobs
                    └─────────┬─────────┘
                              ▼
              Channel adapters (Twilio SMS · WhatsApp · Resend Email)
                              ▲
                    Inbound webhooks (Twilio) with STOP opt-out handling
                              │
                    ┌─────────▼─────────┐
                    │ Conversational Agent│  DeepSeek tool calling:
                    │                     │  confirm · cancel · reschedule
                    └─────────┬─────────┘  (confirmation guardrail in code)
                              │
              Owner dashboard (React SPA): settings · inbox · approval queue
```

## Stack

| Layer | Tech |
|---|---|
| Backend | Python 3.13, FastAPI, SQLAlchemy 2.0, APScheduler |
| LLM | DeepSeek (`deepseek-chat`) via OpenAI-compatible API |
| Messaging | Twilio (SMS/WhatsApp REST), Resend (email) |
| Frontend | Vite + React + TypeScript + Tailwind |
| Infra | Docker, Terraform → ECS Fargate, RDS Postgres, ALB, CloudFront |

## Quick start

```powershell
cd backend
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
.venv\Scripts\pytest          # 44 tests, no credentials needed
.venv\Scripts\uvicorn app.main:app --reload

cd ../frontend
npm install
npm run dev                   # http://localhost:5173
```

All external services (DeepSeek, Twilio, Resend, Google) are behind injectable
protocols with stub/fake implementations — the full test suite runs offline.

## Repo layout

- `backend/` — FastAPI app, agents, scheduler, channels, tests ([README](backend/README.md))
- `frontend/` — React SPA (login, settings, inbox, appointments)
- `infra/` — Terraform for AWS (ECS api+worker, RDS, ALB, S3/CloudFront, alarms)

## CI/CD

- **CI** on every push/PR: backend pytest, frontend typecheck+build, terraform validate
- **Deploy**: pushes to `main` build/push the image to ECR, sync SPA to S3, run
  `terraform apply` (environment-gated; requires OIDC role and secrets)

## Compliance

TCPA-aware: `STOP` opt-out handled before any AI processing, consent records kept,
send-window checks, Twilio webhook signature validation.
