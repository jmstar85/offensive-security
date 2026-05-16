# Mobile Application Pentest — Knowledge Pack

Focus: APK/IPA static surface + dynamic-on-emulator analysis.

## Acquisition (passive_no_target_contact)

- **APK** — public Play Store URL → use `gplaycli` / public APKPure mirror.
  Never sideload from untrusted sources.
- **IPA** — App Store deep link; usually requires a paid Apple Developer
  account or operator-supplied build.
- **Operator-supplied build** — preferred path; store under
  `artifacts/<project>/<platform>/<version>`.

## Static surface (passive_low_touch)

- **Manifest** — `AndroidManifest.xml` for permissions, exported
  activities/services/receivers, `android:debuggable`,
  `android:networkSecurityConfig`.
- **Info.plist** — iOS equivalent: `NSAppTransportSecurity` exceptions,
  `LSApplicationQueriesSchemes`, URL schemes (deep links).
- **Embedded secrets** — `strings` + 48-pattern regex catalog from
  the secret-scan tool. Hard-coded API keys / OAuth secrets are a common find.
- **Third-party SDK inventory** — Firebase, AppsFlyer, Branch, Mixpanel etc.
  Each SDK has its own CVE history.
- **Bytecode analysis** — `apktool` decompile + `jadx` for Java/Kotlin;
  `class-dump` + `Hopper` patterns for iOS (manual).

## Dynamic surface (active_exploit, emulator-only)

- **Frida hooks** — runtime function tracing on rooted/jailbroken emulator.
  Only on operator-supplied builds; never against production app store builds.
- **Objection** — wraps Frida for common payloads (cert-pinning bypass,
  keychain dump, biometric bypass).
- **Burp + proxy CA** — capture TLS-pinned traffic via `frida -l unpinning`
  scripts.

## Common vulnerability classes

1. **Insecure data storage** — SharedPreferences cleartext, NSUserDefaults
   cleartext, SQLite without SQLCipher.
2. **Improper platform usage** — exported activities accepting untrusted
   intents, URL-scheme hijacking, custom-tab cookie leak.
3. **Insecure communication** — missing TLS cert pinning, weak cipher
   suites, mixed content.
4. **Insecure authentication** — credentials in code, missing biometric
   re-auth, refresh-token persistence in plain storage.
5. **Code tampering / lack of integrity checks** — re-signing acceptance,
   missing root/jailbreak detection.
6. **Reverse engineering** — missing obfuscation (R8/ProGuard, Swift Shield).

## Out-of-scope guards

- Never test against production app store builds — only operator-supplied
  builds or sideload-able dev builds with written authorization.
- Never test on a real customer device.
- No automated abuse of in-app purchases (StoreKit / Play Billing).
