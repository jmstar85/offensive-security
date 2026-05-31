# E2E Attack Vector Tests (W4/PR4.5)

Per-vector end-to-end harness covering XSS, SQLi, CSRF, SSRF, IDOR, and CMDI against DVWA and Juice Shop.

## Prerequisites

Both `OSA_E2E_DVWA_URL` and `OSA_E2E_JUICE_URL` must be set. Without them every test in this folder is automatically skipped.

## Quick Start

### DVWA

```bash
docker run -d -p 8080:80 vulnerables/web-dvwa
export OSA_E2E_DVWA_URL=http://localhost:8080
```

### Juice Shop

```bash
docker run -d -p 3000:3000 bkimminich/juice-shop
export OSA_E2E_JUICE_URL=http://localhost:3000
```

### Run the suite

```bash
OSA_E2E_DVWA_URL=http://localhost:8080 \
OSA_E2E_JUICE_URL=http://localhost:3000 \
pytest tests/e2e -v
```

Optional overrides:

| Env var | Default | Purpose |
|---|---|---|
| `OSA_E2E_BACKEND_URL` | `http://localhost:8000` | OSA backend base URL |
| `OSA_E2E_TIMEOUT_S` | `300` | Per-session poll timeout (seconds) |

## Expected Per-Vector Evidence

| Vector | Test class | Target | Finding `type` | Audit action prefix |
|---|---|---|---|---|
| XSS | `TestXSSVector` | DVWA + Juice Shop | `dom_xss_probe` | `session_` |
| SQLi | `TestSQLiVector` | DVWA | contains `sqli` | — |
| CSRF | `TestCSRFVector` | DVWA | `csrf_form_replay` | — |
| SSRF | `TestSSRFVector` | Juice Shop | `oob_callback` or `correlation_id` present | — |
| IDOR | `TestIDORVector` | Juice Shop | type contains `idor` OR severity contains `auth` | — |
| CMDI | `TestCMDIVector` | DVWA | `command_injection` | — |

## When to Run

- **Pre-W4-merge dress rehearsal** — run once against local DVWA + Juice Shop containers before raising the W4 merge PR.
- **72-hour staging soak** — run against production-equivalent tuple T4 for the full soak period as required by v1.1 SF-CRITIC-4.

## CI Behaviour

Tests are skipped by default when the env vars are absent. The shim test `tests/unit/test_e2e_harness_import.py` runs in every CI build to confirm the module is importable without network access.
