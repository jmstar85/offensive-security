# Network Penetration Testing — Knowledge Pack

Focus: external + internal network surface, service-level enumeration,
authenticated and unauthenticated lateral movement.

## Discovery layers

1. **Reachability** — ICMP/ARP discovery (when on-net), nmap `-sn` ping sweep.
2. **Service map** — nmap `-sV -sC -O --open -T4`, restricted port lists per
   engagement profile (1-hour=top1000, 1-day=full 65535).
3. **UDP** — only when explicitly in scope (slower, noisier).

## Service-class playbooks

- **SSH (22)** — banner fingerprint, weak host-key reuse, public-key auth
  vs password auth. Never run bruteforce without `approved_active_exploit`.
- **SMB (139/445)** — null session enumeration, share listing, `enum4linux-ng`
  for local admin/null. Capture authentication banner for OS detection.
- **RDP (3389)** — NLA enforcement, `BlueKeep` / `DejaBlue` CVE check via
  Nuclei. Bruteforce is allowlisted only.
- **DNS (53)** — zone transfer attempt (`dig axfr`), recursive resolution
  check (NXNS), DNSSEC validation.
- **SMTP (25/587)** — VRFY/EXPN enumeration, open-relay test (limited to
  one canary message), STARTTLS downgrade check.
- **HTTP(S) (80/443/8080/8443)** — handed off to the Web pack.
- **Database (1433/3306/5432/27017/6379)** — service banner only at recon
  tier; authenticated checks require explicit credential injection.

## Internal-only signals

When tester is on-net (VPN or jump host):

- **mDNS / LLMNR / NBT-NS** — passive packet capture for responder-style
  hashes. Active spoofing is `active_exploit` only.
- **Active Directory** — `ldapsearch` anonymous bind, BloodHound collection
  (SharpHound) with read-only edges.
- **DHCP** — option 119 (domain search), option 252 (WPAD) — both reveal
  internal naming and proxy posture.

## Common pivots

- **Misconfigured backups** — SMB shares with `*.bak`, `*.old`, `*.zip`
  containing credentials.
- **Printer leaks** — JetDirect (9100), IPP (631), default admin pages.
- **VoIP** — SIP enumeration via `svmap`, default extensions/PINs.
- **Industrial protocols** — Modbus (502), DNP3 (20000), Siemens S7 (102).
  Tier `active_recon` only; never write/control commands.

## Defensive observations to capture

- Open services not in inventory (asset-discovery gap).
- Self-signed or expired TLS certificates.
- Default credentials still in place (banner usually betrays it).
- Outdated firmware/OS versions with KEV-listed CVEs.

## Out-of-scope guards

- Layer-2 attacks (ARP spoofing, DHCP starvation) require an additional
  written authorization beyond the standard RoE.
- Wireless attacks (deauth, WPA3 dictionary) are out of scope by default.
- Any traffic toward `169.254.0.0/16`, `224.0.0.0/4`, or known third-party
  CDNs is blocked at the orchestrator's whitelist layer.
