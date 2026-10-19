# Deployment Guide

This repo deploys in two supported ways:

## Option A — docker compose (single host)

```bash
cp .env.example .env
nano .env                       # set SECRET_JWT_KEY, GATEWAY_API_KEY, ADMIN_*, CORS_ORIGINS
docker compose up -d --build    # backend :8000, frontend :3000, postgres :5432, gateway (sim mode)
docker compose logs -f backend  # confirm migrations + seed
```

Entry points:

- backend (uvicorn, 4 workers)
- frontend (next standalone server on :3000)
- postgres (data volume `postgres-data`)
- gateway (optional; runs with `--simulate` when no radio — remove service for hardware mode)

Put a reverse proxy (Caddy/Traefik/nginx) in front for TLS. Example Caddyfile:

```
ess.example.com {
    # dashboard
    handle {
        reverse_proxy 127.0.0.1:3000
    }
    # API + WS go to uvicorn (WebSocket upgrades work out of the box)
    handle /api/* {
        reverse_proxy 127.0.0.1:8000 {
            header_up X-Forwarded-Proto https
        }
    }
}
```

## Option B — native processes

1. **Postgres** — host yourself; set `DATABASE_URL=postgresql+asyncpg://user:pass@host/db`.
2. **Backend**:
   ```bash
   cd backend && python -m venv .venv && .venv/bin/pip install -r requirements.txt
   .venv/bin/alembic upgrade head
   .venv/bin/python -m app.db.seed          # admin, gateway key, default rules
   .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
   ```
   (make sure env/.env loaded — see `.env.example`).
3. **Gateway** (Pi):
   ```bash
   cd gateway && .venv/bin/pip install -r requirements.txt            # simulator deps
   .venv/bin/pip install -r requirements-lora.txt                     # hardware deps (Pi only)
   .venv/bin/python -m gateway_pkg.main --check                       # sanity
   .venv/bin/python -m gateway_pkg.main                               # run (add --simulate w/o radio)
   ```
4. **Frontend**:
   ```bash
   cd frontend && npm ci && NEXT_PUBLIC_API_BASE_URL=https://ess.example.com/api/v1 npm run build
   PORT=3000 node .next/standalone/server.js
   ```

## systemd units (native mode)

`/etc/systemd/system/ess-backend.service`:

```ini
[Unit]
Description=ESS backend (FastAPI)
After=network-online.target postgresql.service

[Service]
User=ess
WorkingDirectory=/opt/ess/backend
EnvironmentFile=/opt/ess/.env
ExecStart=/opt/ess/backend/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
Restart=always
NoNewPrivileges=true
ProtectSystem=full
ProtectHome=yes
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
```

`ess-gateway.service` similar (`gateway/README.md` shows a complete unit).

## Reverse-proxy checklist

- TLS only (HSTS); no HTTP listeners.
- WS upgrade support (nginx: `proxy_set_header Upgrade $http_upgrade; ...
  Connection "upgrade"`); Caddy/Traefik handle it natively.
- Timeouts generous: WS long-lived (proxy_read_timeout ≥ 120 s).
- Rate limits live in-app already; do not double-limit agent paths.

## Environment checklist

| Var | Must set | Notes |
|-----|----------|-------|
| `SECRET_JWT_KEY` | ✅ | 32+ random bytes (`openssl rand -hex 32`) |
| `DATABASE_URL` | ✅ | `postgresql+asyncpg://...` for prod |
| `GATEWAY_API_KEY` | ✅ | matches frontend gateway config |
| `ADMIN_USERNAME`/`ADMIN_PASSWORD` | ✅ | seeded admin |
| `CORS_ORIGINS` | ✅ | exact list of dashboard scheme+host |
| `COOKIE_SECURE` | prod | true when served over HTTPS |
| `NODE_KEYS` (gateway) | ✅ | per-node hex keys |
| `LORA_*` (gateway) | ✅ | must equal node `config.h` values |
| `NEXT_PUBLIC_API_BASE_URL` | ✅ | as reachable from browsers |

## Post-deploy smoke test

```bash
curl -s https://ess.example.com/api/v1/health
# login and hit me:
curl -s -X POST https://ess.example.com/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"<admin>","password":"<pass>"}' | head -c 300
# gateway end-to-end (simulator):
python -m gateway_pkg.main --simulate &   # then watch the Live page
```

Rollback: keep the previous image tag; `docker compose up -d --no-deps backend`.
Alembic migrations are one-way; database snapshots (see backup doc) are the
rollback anchor.
