# GCP Cloud Pentest — Knowledge Pack

Focus: external GCP surface, GCP IAM read-only validation.

## External fingerprinting (passive_low_touch)

- **Cloud Storage** — `https://storage.googleapis.com/<bucket>/`,
  `gs://<bucket>` enumeration via `cloudenum` GCS module.
- **Cloud Run** — `https://<service>-<hash>-<region>.a.run.app`. URL pattern
  leaks region; banner reveals technology.
- **Cloud Functions** — `https://<region>-<project>.cloudfunctions.net/<fn>`.
- **App Engine** — `https://<project>.appspot.com`, default-service vs
  named-services routing.
- **Firebase** — `https://<project>.firebaseio.com/.json` (legacy RTDB),
  public Firestore reads via `firebase.database()` JS.

## Service account fingerprints (passive_no_target_contact)

- **Public OAuth client IDs** — `*.apps.googleusercontent.com` in HTML.
- **Compute Engine metadata leak** — same SSRF pattern as AWS IMDSv1 but at
  `metadata.google.internal/computeMetadata/v1/`.
- **GKE control plane** — public `/healthz`, `/livez` endpoints when cluster
  is unintentionally exposed.

## Post-credential validation (active_exploit — read-only)

- **gcloud auth list** — confirm credential validity.
- **`projects.list` via IAM API** — enumerate visible projects.
- **`projects.getIamPolicy`** — read bindings only.
- **Service account key rotation status** — flag SA keys older than 90 days
  as a hygiene finding.

## Common pitfalls (KEV-aligned)

- **Misconfigured Cloud SQL** — `0.0.0.0/0` allowed-network ranges.
- **Public Pub/Sub topics** — subscribers can be created by anyone.
- **Default GKE node service account** — broad project-wide scope.
- **VPC peering misroutes** — internal-only data exposed across regions.

## Out-of-scope guards

- Never call `*.delete`, `*.create`, `*.update`, `*.patch` against any GCP
  resource without `approved_active_exploit` + admin role.
- BigQuery enumeration confined to public datasets only.
- Cloud Identity (Workspace) tenant attacks require separate authorization.
