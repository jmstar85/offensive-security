# Web Application Pentest — Knowledge Pack

Focus: pre-auth surface, auth flows, common server-side vulnerabilities.

## Discovery (passive_low_touch)

- **HTTP fingerprinting** — capture `Server`, `X-Powered-By`, security headers
  (HSTS, CSP, X-Content-Type-Options, X-Frame-Options, Referrer-Policy).
- **robots.txt + sitemap.xml** — endpoint enumeration without crawling.
- **`.well-known/` paths** — `security.txt`, `change-password`, OIDC discovery,
  Apple App Site Association, web finger.
- **Source map disclosure** — `*.js.map` reveals internal module paths and
  sometimes secrets.
- **Wappalyzer-style fingerprint** — framework/CMS detection from response
  headers, cookies, and HTML markers.

## Active recon

- **Subdomain enumeration** — subfinder (passive sources) + dnsx
  (resolution + record types). Always cross-check CT logs first.
- **Path enumeration** — `httpx --status-code` against curated wordlists.
  Restricted to short, focused lists; never `dirbuster-medium` style.
- **JS endpoint mining** — extract URLs from JavaScript bundles, then
  request-only-OPTIONS each before any GET.

## Common vulnerability classes (tier `active_recon` → `active_exploit`)

1. **Authentication** — missing rate limits, weak password reset (token
   guessability, token leakage in referer), session fixation, JWT `alg=none`.
2. **Authorization (IDOR)** — predictable IDs, missing object-level checks,
   tenant boundary leaks in multi-tenant apps.
3. **Injection** — SQLi, command injection, NoSQL injection, LDAP injection,
   SSTI. Use Nuclei templates first; never use destructive payloads.
4. **SSRF** — open redirect → SSRF, blind SSRF via webhook endpoints,
   cloud-metadata exposure (169.254.169.254).
5. **XSS** — DOM-based, stored, reflected. Confirm only with proof-of-concept
   payloads that don't persist.
6. **Deserialization** — Java/.NET/PHP/Ruby unsafe deserialization patterns.
7. **File handling** — path traversal, upload bypass (content-type, extension,
   double-extension), file inclusion (LFI/RFI).
8. **Business logic** — race conditions in checkout/transfer flows, coupon
   reuse, negative quantity, currency rounding.

## Vendor-fingerprint shortcuts

- **Citrix Netscaler** — `/vpn/index.html`, `/logon/LogonPoint/index.html`.
- **F5 BIG-IP** — `/tmui/login.jsp`, `BIGipServer*` cookies.
- **Pulse Secure / Ivanti** — `/dana-na/auth/url_default/welcome.cgi`.
- **FortiGate SSL VPN** — `/remote/login`, `/sslvpn/portal.html`.
- **Microsoft Exchange OWA** — `/owa/`, `/Microsoft-Server-ActiveSync`.

When any vendor signature matches, enrich with the appropriate KEV CVE list
+ EPSS score before deciding tier (recon vs exploit).

## Out-of-scope guards

- Never run `nuclei -t fuzzing/` or `dos/` templates regardless of approvals.
- Block `wp-config.php`, `.git/`, `.env` direct fetches at planner stage — log
  but do not request without an explicit operator approval per session.
- All HTTP requests pass through `passive_egress_allowlist` for passive tier
  containers; active containers use the project's `active_allowed` list.
