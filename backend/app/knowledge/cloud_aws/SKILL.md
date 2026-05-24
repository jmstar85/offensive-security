# AWS Cloud Pentest — Knowledge Pack

Focus: external AWS surface + post-credential read-only validation.
Active exploitation (write actions, role assumption chains) requires explicit
`approved_active_exploit` and admin role.

## External AWS fingerprinting (passive_low_touch)

- **Account-ID extraction** — public S3 URLs, public Lambda ARNs in HTML,
  CloudFront origin IDs leaking the account.
- **Region inference** — `s3.<region>.amazonaws.com`, `<id>.execute-api.<region>`,
  `<id>.lambda-url.<region>`, MediaConvert/MediaStore endpoint patterns.
- **Public buckets** — `cloudenum` against the company stems × 47 suffixes.
  Read `ListObjects` only on public buckets; never write.
- **Lambda Function URLs** — `https://<id>.lambda-url.<region>.on.aws/`. Probe
  with HTTP OPTIONS only; CORS misconfig is recon-tier.
- **CloudFront / API Gateway** — origin discovery via header replay, S3
  origin leak through `x-amz-id-2`.

## Credential validation (active_exploit — read-only)

Validators that never mutate state. Each lives inside the
`osa-passive-recon:latest` shared image:

- **STS GetCallerIdentity** — confirms a key is live, reveals account ID +
  ARN (user vs role).
- **IAM `ListAttachedUserPolicies` / `ListAttachedRolePolicies`** — only if
  the key has the permission; do not call `Simulate*Policy`.
- **S3 `ListBuckets`** — quick blast-radius read; never `PutObject` or
  `DeleteBucket`.

If any validator returns evidence of write permissions, surface that as a
**finding** with severity High and stop. Do not exercise the write.

## Post-discovery enumeration (active_recon)

When an unauthenticated EC2 instance metadata service (IMDSv1) is exposed via
SSRF, capture:

1. `iam/security-credentials/` — role names only at this step.
2. Confirm with operator before fetching short-term credentials.

## Sentinel CVEs (KEV-tagged)

Refresh quarterly. Examples:

- **CVE-2021-44228** (Log4Shell) — exposed Java services on EC2/ECS.
- **CVE-2023-3519** (Citrix on AWS Marketplace AMIs).
- **CVE-2024-3094** (xz backdoor) — check provisioning AMIs and ECR images.

## Out-of-scope guards

- Never call any AWS action that mutates state (`Put*`, `Delete*`, `Create*`,
  `Modify*`, `Detach*`) without `approved_active_exploit` flag + admin role.
- `s3:*` enumeration confined to operator-provided customer ID prefix.
- Cross-account `sts:AssumeRole` attempts require explicit operator approval.
