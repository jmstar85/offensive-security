# Azure Cloud Pentest — Knowledge Pack

Focus: Entra ID (Azure AD) / M365 tenant surface, Azure resource surface.

## Tenant fingerprinting (passive_no_target_contact)

- **Entra tenant discovery** — `https://login.microsoftonline.com/<domain>/.well-known/openid-configuration`
  reveals tenant GUID and federation posture (managed vs federated).
- **GetUserRealm** — `https://login.microsoftonline.com/getuserrealm.srf?login=<user>@<domain>&xml=1`
  returns NameSpaceType (Managed / Federated / Unknown).
- **Microsoft Online API** — `https://login.microsoftonline.com/common/userrealm/<user>?api-version=2.1`
  also enumerates user existence with rate-limit caveats.
- **Domain federation chain** — `https://autodiscover-s.outlook.com/Autodiscover/Autodiscover.svc`
  reveals SAML/ADFS endpoints.

## M365 service enumeration (passive_low_touch)

- **Teams federation** — `https://teams.microsoft.com/api/mt/<region>/beta/users/<user>@<domain>/externalsearchv3`
  (requires authenticated client; use sparingly).
- **SharePoint** — `https://<tenant>.sharepoint.com/_layouts/15/RpcProxy.aspx`,
  `<tenant>-my.sharepoint.com` for OneDrive presence check.
- **Skype/Lync** — `https://lyncdiscover.<domain>` legacy fingerprint.
- **OAuth device-code** — `/common/oauth2/devicecode` discovery; probe only.

## Resource-surface fingerprinting (passive_low_touch)

- **Azure Storage** — `https://<account>.blob.core.windows.net/`, container
  list via anonymous `?restype=container&comp=list` (where public).
- **App Service** — `https://<app>.azurewebsites.net`, banner check.
- **Function Apps** — `https://<app>.azurewebsites.net/api/<func>` plus
  `/admin/host/status` for misconfigured hosts.
- **CDN endpoint takeover** — dangling `*.azureedge.net` CNAMEs.

## Active recon

- **Subdomain bruteforce** — `<tenant>-*.azurewebsites.net`,
  `<account>.<region>.cloudapp.azure.com` style patterns.
- **Microsoft Graph** — anonymous `/v1.0/$metadata` confirms tenant
  existence; never call beyond metadata without explicit authorization.

## Post-credential (active_exploit — read-only)

- **WhoAmI via Graph** — `/me` returns user object + tenant info.
- **Role enumeration** — `/me/memberOf` returns groups + directory roles.
- **Stop on write capability** — same rule as AWS: if `Application.ReadWrite.All`
  or similar appears, raise finding and stop.

## Out-of-scope guards

- Never trigger `Authentication Method` changes, MFA prompts, or password
  resets — these create user-visible noise and may violate engagement RoE.
- Conditional Access bypass attempts require an explicit signed amendment.
- Token-replay attacks against M365 require admin role + approval.
