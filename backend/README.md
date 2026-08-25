# Appointment Reminder Agent — Backend

Multi-tenant appointment reminder agent backend. See `../../PRD.MD` for requirements.

## Layout

- `app/models` — SQLAlchemy 2.0 entities (Tenant, Customer, Appointment, ReminderJob, Conversation, Message, PendingAction, ConsentRecord)
- `app/calendar_sync` — Google Calendar client protocol + event→Appointment sync + free-slot search
- `app/scheduler` — idempotent reminder job generation + APScheduler dispatch cycle
- `app/agents` — DeepSeek conversational agent (tool calling, mockable LLM protocol)
- `app/channels` — outbound adapters: Twilio SMS/WhatsApp, Resend email (+ dev stubs)
- `app/api` — auth (JWT), dashboard, admin approval queue, Twilio webhook
- `infra/` — Terraform: ECS Fargate (api+worker), RDS Postgres, ALB, S3/CloudFront, alarms

## Setup (dev)

```powershell
cd backend
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
.venv\Scripts\pytest
.venv\Scripts\uvicorn app.main:app --reload
```

Google Calendar live sync requires the optional extra: `pip install -e ".[google]"`.
DeepSeek live calls require the `[llm]` extra plus `DEEPSEEK_API_KEY`.

## Docker

```powershell
# from backend/
docker build -f Dockerfile.backend -t ara-backend .
docker run -p 8000:8000 -e APP_DATABASE_URL=sqlite:///./app.db ara-backend
```

Worker variant (same image): command `python -m app.worker` — see `infra/ecs.tf`.

## Production environment variables

Set via AWS Secrets Manager / SSM (see `infra/secrets.tf`, `infra/rds.tf`):

| Variable | Purpose |
|---|---|
| `APP_DATABASE_URL` | Postgres connection string |
| `APP_JWT_SECRET` | HS256 key, ≥32 bytes |
| `DEEPSEEK_API_KEY` | Conversational agent |
| `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` / `TWILIO_SMS_FROM` / `TWILIO_WHATSAPP_FROM` | Outbound SMS/WhatsApp; token also enables webhook signature validation |
| `RESEND_API_KEY` / `RESEND_FROM` | Transactional email |
| `APP_CORS_ORIGINS` | Allowed SPA origins |

## Infrastructure & CI/CD

Validate Terraform locally (avoids path-with-spaces mount issues):

```powershell
docker run --rm --entrypoint sh -v <abs-path-to-infra>:/workspace -w /workspace `
  hashicorp/terraform:1.9 -c "terraform init -backend=false && terraform validate"
```

- `.github/workflows/ci.yml` — pytest + frontend build + terraform validate on every push/PR.
- `.github/workflows/deploy.yml` — ECR push + SPA sync + terraform apply on main (environment-gated OIDC).
