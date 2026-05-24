# Claude-OSINT Onboarding Feasibility

## Source reviewed

- Candidate repository: `elementalsouls/Claude-OSINT`
- License observed: MIT License with an additional offensive-security use notice.
- Structure observed from public metadata: paired Claude skills (`osint-methodology`, `offensive-osint`), public recon methodology, dork/regex catalogs, read-only validators, and attack-path templates.

## Feasibility decision

Claude-OSINT is **feasible to onboard as OSA-native methodology, workflow templates, and eventually a passive OSINT domain agent**, but it should not be imported wholesale in the v3.2.1 stabilization pass.

The current OSA execution substrate only supports registry-backed runtime agents (`nmap`, `nuclei`, `metasploit`, `pyrit`). Workflow execution, ownership checks, and schema normalization must be reliable before adding a broader OSINT runtime surface.

## Recommended migration model

1. **Reference/template phase**
   - Add passive OSINT workflow templates that use existing executable agents where possible.
   - Add methodology notes and UI copy for authorized reconnaissance only.
   - Keep third-party-derived text out of code unless attribution and review are complete.

2. **OSA-native OSINT domain agent phase**
   - Implement a clean-room `osint` adapter with explicit passive-only boundaries.
   - Normalize output into the existing findings/reporting pipeline.
   - Add scope checks for domains, organizations, and public sources before collection.

3. **Expanded knowledge module phase**
   - Curate OSA-owned checklists for identity, cloud exposure, email security, web attack surface, and secret exposure.
   - Add license attribution if any MIT-licensed source material is adapted.

## Safe candidates

- External recon methodology and time-boxed workflow templates.
- Asset graph concepts for domains, subdomains, IP ranges, cloud assets, and identity providers.
- Passive public-source checks for DNS, HTTP metadata, TLS/cert transparency, email security records, and public code exposure for user-owned assets.
- Reporting rubrics and confidence scoring adapted into OSA's report model.

## Excluded from this pass

- Copying Claude-OSINT skill content directly into OSA.
- Credential validation against third-party services.
- Active exploitation, intrusive probing, credential attacks, or social engineering automation.
- Runtime OSINT agent execution before workflow safety, scope checks, and tests are in place.

## Next implementation slice

After v3.2.1 stabilization, add a passive `osint` catalog entry and a non-runtime template first. Then implement a runtime adapter only after safety controls and output schemas are defined.
