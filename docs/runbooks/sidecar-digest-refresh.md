# Sidecar Image Digest Refresh — Operator Runbook

## Schedule

The workflow `sidecar-digest-refresh-quarterly.yml` runs automatically on the first day of each quarter at 04:00 UTC:

| Quarter | Date       |
|---------|------------|
| Q1      | January 1  |
| Q2      | April 1    |
| Q3      | July 1     |
| Q4      | October 1  |

Cron expression: `0 4 1 1,4,7,10 *`

## Manual Trigger Procedure

1. Navigate to **Actions → Sidecar Image Digest Refresh (Quarterly)** in GitHub.
2. Click **Run workflow**.
3. Optionally specify a single sidecar (`mitmproxy`, `headless-browser`, or `interactsh`); leave blank to refresh all three.
4. Click **Run workflow** to confirm.

The workflow opens one PR per sidecar with the new digest value.

## Reviewing the Auto-Generated PR

Each PR updates one `OSA_*_DIGEST` build arg in `docker-compose.yml`. Before approving:

1. **Digest sha256 validates** — confirm the new digest matches `sha256:[a-f0-9]{64}`. The workflow step "Verify digest format" enforces this; check the Actions log.
2. **Image-regex unchanged** — the image name in the matrix entry (`mitmproxy/mitmproxy`, `mcr.microsoft.com/playwright`, `projectdiscovery/interactsh-server`) must not have changed. Any image rename is a red flag requiring a separate security review.
3. **SBOM diff inspected** — run `docker sbom <image>@<new-digest>` locally and diff against the previous digest's SBOM. Flag any new packages or removed packages for a security review before merging.
4. **No extra published ports** — confirm the sidecar's Dockerfile and compose service definition still expose only the expected ports. New `EXPOSE` directives must be reviewed.
5. **Upstream changelog skim** — check the upstream release notes (GitHub releases or CHANGELOG) for any breaking changes, CVE fixes, or behavioral changes relevant to the OSA attack pipeline.

## Rollback Procedure

If a newly merged digest introduces a regression (test failures, unexpected behavior, security concern):

1. Identify the digest commit SHA: `git log --oneline --grep="refresh OSA_"`.
2. Revert the commit: `git revert <sha>` and open a PR against `main`.
3. After the revert merges, trigger a backend redeploy — it will pull the image using the previous digest pinned in `docker-compose.yml`.
4. File a tracking issue describing the regression before the next quarterly refresh.

## SLA

Digest-refresh PRs must land within **7 days** of the workflow mint date. If the PR is not merged within 7 days, the on-call engineer is responsible for either merging or raising a blocking issue explaining the delay.
