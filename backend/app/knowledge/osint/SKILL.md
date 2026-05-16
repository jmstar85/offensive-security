# OSINT Recon — Knowledge Pack

Focus: open-source intelligence gathering with zero direct target contact.

## Asset graph seeds

- **Primary domain** — operator-supplied.
- **Sibling domains** — WHOIS reverse, RDAP, historical-WHOIS (DomainTools,
  ViewDNS).
- **Cloud accounts** — AWS account ID, GCP project ID, Azure tenant GUID
  (when known).
- **Source code organizations** — GitHub, GitLab, Bitbucket, Azure DevOps.

## Subdomain enumeration

- **Certificate Transparency** — crt.sh (primary), Sectigo CT, Google CT.
  Use SQL-style queries: `SELECT name_value FROM certificate_identity
  WHERE reverse(lower(name_value)) LIKE reverse(lower('%.target.tld'))`.
- **Passive DNS** — VirusTotal `/domains/<domain>/subdomains`, SecurityTrails
  free tier, SANS ISC.
- **Wayback CDX** — historical paths and subdomains via
  `https://web.archive.org/cdx/search/cdx?url=*.target.tld&output=json`.
- **Search-engine dorks** — `site:target.tld -www`, `inurl:` enumeration.

## Public records

- **OpenCorporates** — corporate entity registry, ownership chain.
- **SEC EDGAR** — US public companies' filings; reveals subsidiaries and
  acquired entities (useful for in-scope expansion).
- **Companies House (UK)** — directors, officers, registered addresses.
- **EU OpenCorporates clones** — country-specific gateways.
- **SAM.gov** — US federal contracting, useful for `.gov`/`.mil` targets.

## Identity-fabric mapping

- **SSO posture** — Entra (Azure AD), Okta tenant slug, ADFS metadata
  paths, generic OIDC discovery (Auth0, Keycloak, Ping, OneLogin, Duo).
- **Email pattern inference** — 8 common formats: `first.last@`,
  `flast@`, `firstl@`, `first_last@`, plus organization-specific patterns
  derived from LinkedIn employee scrapes.
- **Employee enumeration** — LinkedIn role tiers, OSINT sockpuppet
  hygiene (separate browser profile, no cross-contamination of cookies).

## Source code & dependency leaks

- **GitHub code search** — 13 templates for org-scoped + filename-scoped
  + extension-scoped secret hunts. Always read-only; never clone private
  repos that surface unintentionally.
- **Package registries** — npm/PyPI/RubyGems/Crates/Maven/NuGet for
  typo-squat surveillance and credential leaks in published packages.
- **Postman public workspaces** — search for organization name.
- **Stack Exchange OSINT** — Stack Overflow + 7 sister sites for
  developer-leaked snippets.

## Breach intelligence

- **HudsonRock Cavalier** — public JSON endpoint mapping breached
  credentials to corporate domains.
- **HaveIBeenPwned** — domain-level breach existence check.
- **IntelX / DeHashed** — operator-account-only; never share raw breach
  data outside the engagement.

## Out-of-scope guards

- All sources accessed only via `passive_egress_allowlist` (no
  authenticated direct probing of target infrastructure).
- Do not scrape paid intelligence sources beyond the operator's licensed
  account.
- LinkedIn employee enumeration is for organization-only mapping; do not
  attempt to friend, follow, or message identified employees.
