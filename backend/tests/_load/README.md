# Load Harness — SF-CRITIC-1 v1.1

This directory contains the load-test harness for the multi-user pentest session flow.
It was explicitly required by the v1.1 plan SF-CRITIC-1 acceptance criteria and is NOT a generic README.

## Starting the load stack

```bash
docker compose -f docker-compose.yml -f docker-compose.load.yml up -d backend locust k6
```

## Viewing results

- **Locust web UI**: http://localhost:8089 (live charts while the run is active)
- **CSV results**: `backend/.omc/state/load-run_stats.csv` and `load-run_stats_history.csv`
- **k6 stdout**: `docker compose -f docker-compose.yml -f docker-compose.load.yml logs k6`

## SLO targets

| Metric | Target |
|---|---|
| Locust `end_to_end_session_start` p95 latency | < 2500 ms over 60 s of 100-user sustained load |
| k6 WebSocket `ws_session_duration` p95 | < 2500 ms |

## Credential-isolation check

After the run, verify that no credential plaintext leaked into audit logs:

```bash
curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
  "http://localhost:8000/api/v1/audit-logs?limit=10000" \
  | grep -c "loadtest-pw"
# Expected output: 0
```

A non-zero result is a blocker — do not promote to staging until resolved.

## When to run

- Pre-W2b-merge dress rehearsal (local stack against `feat/kali-coexistence-v1`)
- 48-hour staging soak before T3 production rollout
- After any change to `pentest-sessions/start`, `projects`, or WebSocket session routing
