# Credential Fernet Key Rotation Runbook

## When to Rotate

- **Quarterly (automated):** GitHub Actions workflow runs at 03:00 UTC on the 1st of Jan/Apr/Jul/Oct.
- **On-suspicion (manual):** Trigger `workflow_dispatch` immediately if a key compromise is suspected or `credential_decryption_failed_total` spikes unexpectedly.

## Pre-Rotation Checklist

- [ ] KMS service healthy (AWS KMS / GCP KMS / Azure Key Vault — check provider status page)
- [ ] Staging soak passing: MultiFernet decrypts all existing test credentials
- [ ] Current `OSA_CREDENTIAL_FERNET_KEYRING` has fewer than `MAX_KEY_RING_SIZE` (3) entries
- [ ] On-call engineer available for 30-minute rotation window

## Rotation Steps

1. **Mint** — provision a new Fernet key via KMS `GenerateDataKey`; store wrapped key in secrets manager.
2. **Prepend** — update `OSA_CREDENTIAL_FERNET_KEYRING` secret: new wrapped key at index 0, existing keys shift right. Use `rotate()` from `credential_key_rotation.py`.
3. **Redeploy** — rolling restart of backend so all pods load the new keyring.
4. **Background re-encrypt** — trigger the re-encryption job (reads each `UserLLMCredential`, decrypts with MultiFernet, writes back encrypted under new current key).
5. **24h grace** — leave the old key at index 1 for one full day so in-flight tokens decrypt cleanly.
6. **Purge tail** — after grace period, drop any key beyond index `MAX_KEY_RING_SIZE - 1` from the keyring secret and redeploy.

## Rollback

If the new key causes decryption failures:

1. Remove the new key from index 0 of `OSA_CREDENTIAL_FERNET_KEYRING`.
2. The previous key (originally at index 1) becomes index 0 — it is now the current encrypting key again.
3. Redeploy backend.
4. Rollback completes in under 10 minutes.

## Audit Signals to Watch

| Signal | Meaning |
|---|---|
| `credential.fernet_key_rotated` | Rotation completed; logged to audit trail |
| `credential_decryption_failed_total` | Rising count → key mismatch or corruption; consider rollback |
| `credential_reencrypt_job_completed` | Background re-encryption finished |

## SLAs

- Full rotation (mint → redeploy → re-encrypt confirmed): **< 30 minutes**
- Rollback (remove new key → redeploy): **< 10 minutes**
