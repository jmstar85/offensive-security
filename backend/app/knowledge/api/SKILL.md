# API Security Pentest — Knowledge Pack

Focus: REST + GraphQL + gRPC endpoints. Authentication, authorization,
rate limiting, schema disclosure.

## Discovery (passive_low_touch)

- **OpenAPI / Swagger** — 28 well-known paths: `/swagger.json`,
  `/swagger/v1/swagger.json`, `/v3/api-docs`, `/openapi.json`,
  `/api-docs.json`, plus framework-specific routes (FastAPI `/docs`,
  Django REST framework `/schema/`, Spring `/v3/api-docs`).
- **GraphQL introspection** — `/graphql`, `/api/graphql`, `/v1/graphql`,
  `/query`. Probe with `{__schema{queryType{name}}}`; if introspection is
  disabled, fall back to field-suggestion enumeration.
- **gRPC reflection** — `grpcurl -plaintext <host>:<port> list`. Reflection
  is rarely intentional in production.
- **API gateway fingerprints** — `X-Kong-Latency`, `X-Tyk-Authorization`,
  `X-RateLimit-*`, `X-Apigee-*` headers.

## Authentication probes (active_recon)

- **API key in header vs query** — many APIs accept both; key in URL
  leaks via referrer and logs.
- **JWT inspection** — `alg=none` and `alg=HS256-with-pubkey-as-secret`
  bypass classics; check for missing `exp`/`nbf` claims.
- **OAuth2 / OIDC** — discovery via `/.well-known/openid-configuration`;
  unusual response types and PKCE absence are recon findings.
- **mTLS** — when present, log the cert-chain requirements; do not attempt
  bypass without an explicit signed amendment.

## Authorization classes (active_recon → active_exploit)

1. **Broken object-level authorization (BOLA / IDOR)** — predictable IDs,
   missing tenant guards, mass-assignment.
2. **Broken function-level authorization** — admin endpoints reachable via
   role-stripped JWTs.
3. **Excessive data exposure** — `/users/<id>` returns full profile when
   only avatar was needed.
4. **Mass assignment** — `PUT /users/<id>` accepting `role: admin` in body.
5. **Lack of rate limiting** — token endpoints, password-reset endpoints,
   2FA verification endpoints.

## Common server-side classes

- **GraphQL N+1 / depth bombs** — cost analysis missing; bring down
  service via deep nesting. **Never run as exploitation**, only document
  the schema vulnerability.
- **REST verb tampering** — `X-HTTP-Method-Override`, `_method=` query
  parameter bypassing method-level ACLs.
- **Cache poisoning** — `X-Forwarded-Host`, `Host` header injection
  reflected in response with cache headers.
- **SSRF via webhook endpoints** — `POST /webhooks` accepting attacker URLs.

## Out-of-scope guards

- Never run dictionary/credential-stuffing against production token
  endpoints — even with `approved_active_exploit`, this requires explicit
  per-endpoint approval in the session config.
- Mass-assignment exploitation must be confined to test accounts only.
- GraphQL introspection on tier `passive_low_touch`; deeper field-suggestion
  enumeration is `active_recon`.
