# OSA Platform — Offensive Security Agent

AI-powered autonomous penetration testing platform for security consultants. Describe a target environment in natural language — the AI orchestrator generates an attack plan, runs tools in Docker containers, streams real-time results, and produces a PDF report.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    React Frontend                        │
│  Login │ Projects │ Prompt Input │ Monitor │ Reports     │
│                    (WebSocket)                           │
└──────────────────────┬──────────────────────────────────┘
                       │ REST + WebSocket
┌──────────────────────▼──────────────────────────────────┐
│                 FastAPI Backend                           │
│  Auth (JWT) │ Projects API │ Sessions API │ Reports API  │
│                                                          │
│  ┌─────────────────────────────────────────────────┐    │
│  │          AI Orchestrator (Claude API)            │    │
│  │  Prompt → Plan → Agent Selection → Execution    │    │
│  │  Safety: Whitelist │ Risk Filter │ Kill Switch   │    │
│  └──────────┬───────────────────────────────────── ┘    │
│             │ Docker SDK                                  │
│  ┌──────────▼──────────────────────────────────────┐    │
│  │         Agent Runner (Docker Containers)          │    │
│  │  ┌──────┐ ┌───────┐ ┌───────────┐ ┌─────────┐  │    │
│  │  │ Nmap │ │Nuclei │ │Metasploit │ │  PyRIT  │  │    │
│  │  └──────┘ └───────┘ └───────────┘ └─────────┘  │    │
│  └──────────────────────────────────────────────────┘    │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│                   PostgreSQL 16                          │
│  users │ projects │ sessions │ executions │ reports      │
│  audit_logs │ targets                                    │
└─────────────────────────────────────────────────────────┘
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18 + TypeScript + Vite + TailwindCSS |
| Backend | Python 3.12 + FastAPI + SQLAlchemy (async) |
| Database | PostgreSQL 16 |
| AI | Claude API (Anthropic SDK) |
| Containers | Docker SDK for Python (docker-py) |
| Real-time | FastAPI WebSocket + asyncio event bus |
| PDF Reports | WeasyPrint |
| Auth | JWT (python-jose + passlib/bcrypt) |

## Features

- **Natural language prompts** — describe a target; Claude generates a structured attack plan
- **4 integrated security tools** — Nmap, Nuclei, Metasploit, PyRIT running in Docker
- **Real-time monitoring** — WebSocket streaming of live agent output with kill switch
- **Layered safety guards** — whitelist enforcement, risk filter, exploit allowlist, egress monitor
- **PDF reports** — auto-generated findings with CVSS scores and remediation guidance
- **Full audit trail** — every AI decision and agent action logged

## Quick Start

### Prerequisites
- Docker 24.0+ and Docker Compose 2.20+
- Anthropic API key

### Setup

```bash
git clone https://github.com/jmstar85/offensive-security
cd offensive-security

# Configure environment
cp .env.example .env
# Edit .env: set ANTHROPIC_API_KEY and SECRET_KEY

# Start services
docker compose up -d postgres
docker compose up backend frontend

# Apply migrations
docker compose exec backend alembic upgrade head

# Open UI
open http://localhost:5173
```

### Pre-build Agent Images

```bash
docker build -t osa-nmap:latest ./docker/nmap
docker build -t osa-nuclei:latest ./docker/nuclei
docker build -t osa-metasploit:latest ./docker/metasploit   # ~2GB
docker build -t osa-pyrit:latest ./docker/pyrit
```

## Safety Architecture

All pentest sessions pass through a 7-layer safety chain:

```
Prompt → [Rate Limit] → [Whitelist] → [AI Plan] → [Exploit Allowlist]
       → [Risk Filter] → [Docker Execution] → [Egress Monitor] → [Audit Log]
```

- **Whitelist Validator** — rejects any IP/domain not in the project's authorized scope
- **Exploit Allowlist** — only pre-approved Metasploit modules and Nuclei templates can run
- **Risk Filter** — blocks CRITICAL-risk steps (DoS, ransomware, data destruction)
- **Kill Switch** — operator can stop all containers within 5 seconds via UI or REST API
- **Egress Monitor** — real-time outbound connection monitoring; auto-kills on violation
- **Audit Log** — every decision logged with actor, timestamp, and details

> ⚠️ **Legal Notice:** This platform executes real security tools against real systems. Always obtain written authorization before running any pentest session. The whitelist technically enforces scope, but legal authorization is the operator's responsibility.

## Project Structure

```
offensive-security/
├── backend/
│   ├── app/
│   │   ├── api/v1/          # FastAPI routers (auth, projects, sessions, reports, ws)
│   │   ├── agents/          # Agent adapters (nmap, nuclei, metasploit, pyrit)
│   │   │   └── backends/    # Docker execution backend
│   │   ├── core/            # Config, database, security, events
│   │   ├── models/          # SQLAlchemy models
│   │   ├── orchestrator/    # AI planner + plan executor
│   │   ├── reports/         # Report generator + PDF
│   │   └── safety/          # Whitelist, risk filter, exploit allowlist, kill switch
│   └── tests/
│       ├── unit/            # Safety + agent unit tests (74 tests)
│       └── integration/     # Pipeline integration tests
├── frontend/
│   └── src/
│       ├── pages/           # Login, Dashboard, Projects, Monitor, Reports
│       ├── api/             # Axios API client
│       └── hooks/           # useWebSocket hook
├── docker/
│   ├── nmap/                # Nmap agent Dockerfile
│   ├── nuclei/              # Nuclei agent Dockerfile
│   ├── metasploit/          # Metasploit agent Dockerfile
│   ├── pyrit/               # PyRIT agent Dockerfile
│   └── targets/             # Vulnerable test target
├── docs/
│   ├── deployment.md        # Deployment guide
│   └── safety.md            # Safety architecture details
└── docker-compose.yml
```

## Running Tests

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install pytest pytest-asyncio aiosqlite sqlalchemy pydantic anthropic docker

PYTHONPATH=. python -m pytest tests/ -v
# → 74 passed in 0.45s
```

## API Reference

FastAPI auto-generates interactive docs at:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

Key endpoints:

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/auth/login` | Authenticate and get JWT token |
| `GET/POST` | `/api/v1/projects` | List / create pentest projects |
| `POST` | `/api/v1/sessions` | Launch pentest session (async) |
| `POST` | `/api/v1/sessions/{id}/kill` | Emergency kill switch |
| `GET` | `/api/v1/reports/{id}` | Get report findings |
| `GET` | `/api/v1/reports/{id}/pdf` | Download PDF report |
| `WS` | `/ws/sessions/{id}` | Real-time session event stream |

## Documentation

- [Deployment Guide](docs/deployment.md)
- [Safety Architecture](docs/safety.md)
