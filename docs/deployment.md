# Deployment Guide — OSA Platform

## Prerequisites

| Tool | Version |
|------|---------|
| Docker | 24.0+ |
| Docker Compose | 2.20+ |
| Python | 3.12+ |
| Node.js | 20+ |

---

## Quick Start (Development)

### 1. Clone and configure

```bash
git clone <repo>
cd offensive-security
cp .env.example .env
# Edit .env — set ANTHROPIC_API_KEY and SECRET_KEY
```

### 2. Start services

```bash
docker compose up -d postgres
# Wait for postgres health check to pass, then:
docker compose up backend frontend
```

### 3. Run database migrations

```bash
docker compose exec backend alembic upgrade head
```

### 4. Create first user

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@example.com", "password": "changeme123", "full_name": "Admin"}'
```

### 5. Access the UI

Open [http://localhost:5173](http://localhost:5173) in your browser.

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Yes | — | PostgreSQL async URL (`postgresql+asyncpg://...`) |
| `SECRET_KEY` | Yes | — | JWT signing key (use `openssl rand -hex 32`) |
| `ANTHROPIC_API_KEY` | Yes | — | Claude API key from console.anthropic.com |
| `ANTHROPIC_MODEL` | No | `claude-sonnet-4-20250514` | Claude model ID |
| `DEBUG` | No | `false` | Enable FastAPI debug mode |
| `DOCKER_NETWORK` | No | `osa_pentest_net` | Docker network name for agent containers |
| `CONTAINER_MEMORY_LIMIT` | No | `512m` | Memory limit per agent container |
| `CONTAINER_CPU_LIMIT` | No | `1.0` | CPU limit per agent container |
| `MAX_PROMPTS_PER_MINUTE` | No | `5` | Rate limit: Claude API calls per user per minute |

---

## Production Deployment

### Docker Compose (single host)

```yaml
# docker-compose.prod.yml
services:
  backend:
    environment:
      DEBUG: "false"
      SECRET_KEY: "${SECRET_KEY}"        # use a real secret
      DATABASE_URL: "${DATABASE_URL}"    # external managed postgres
      ANTHROPIC_API_KEY: "${ANTHROPIC_API_KEY}"
    restart: always
    deploy:
      resources:
        limits:
          cpus: "2"
          memory: 2G
```

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### TLS / Reverse Proxy (nginx example)

```nginx
server {
    listen 443 ssl;
    server_name osa.yourcompany.com;

    ssl_certificate /etc/ssl/certs/osa.crt;
    ssl_certificate_key /etc/ssl/private/osa.key;

    location /api/ {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
    }

    location /ws/ {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    location / {
        proxy_pass http://localhost:5173;
    }
}
```

---

## Building Agent Docker Images

Pre-build the agent images before running pentest sessions:

```bash
# Build all agent images
docker build -t osa-nmap:latest ./docker/nmap
docker build -t osa-nuclei:latest ./docker/nuclei
docker build -t osa-metasploit:latest ./docker/metasploit  # ~2GB, takes ~10 min
docker build -t osa-pyrit:latest ./docker/pyrit

# Build vulnerable test target
docker build -t osa-target:latest ./docker/targets
```

> **Note:** The Metasploit image is ~2GB. Pre-build and push to a private registry to avoid pull delays during pentest sessions.

---

## Database Migrations

```bash
# Apply all pending migrations
alembic upgrade head

# Create a new migration after model changes
alembic revision --autogenerate -m "describe change"

# Rollback one step
alembic downgrade -1
```

---

## Health Checks

```bash
# Backend
curl http://localhost:8000/health
# → {"status": "healthy", "service": "Offensive Security Agent"}

# Database connectivity
docker compose exec postgres pg_isready -U postgres
```

---

## Monitoring & Logs

```bash
# Backend logs
docker compose logs -f backend

# Agent container logs (during active session)
docker logs <container-id>

# Audit log (via API)
curl -H "Authorization: Bearer <token>" \
  http://localhost:8000/api/v1/audit-logs?limit=50
```

---

## Backup

```bash
# Backup PostgreSQL
docker compose exec postgres pg_dump -U postgres osa_db > backup_$(date +%Y%m%d).sql

# Restore
docker compose exec -i postgres psql -U postgres osa_db < backup.sql
```

---

## Security Hardening

1. **Change `SECRET_KEY`** — never use the default dev key in production
2. **Restrict Docker socket access** — the backend mounts `/var/run/docker.sock`; ensure only trusted containers have access
3. **Network isolation** — agent containers run in an isolated Docker network; do not expose this network externally
4. **Rate limiting** — set `MAX_PROMPTS_PER_MINUTE=5` (default) or lower for production
5. **Audit logs** — review `/api/v1/audit-logs` regularly for whitelist violations and kill switch triggers
6. **HTTPS** — always use TLS in production; never expose the API over plain HTTP
