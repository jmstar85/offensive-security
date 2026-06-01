# Runbook: infra.network_membership_violation

**Severity:** CRITICAL PAGE
**Owner:** on-call SRE + Infrastructure Lead
**SLA:** 3 minutes to acknowledge, 10 minutes to isolate

## Symptom

The MF6 runtime check (`_assert_backend_network_membership` in `app/main.py`) detected that the backend container is NOT a member of the expected `osa_pentest_net` Docker network, or a container is a member of a network it should not be on. This check runs at startup and is also enforced by the docker-socket-proxy filter in `app/infra/socket_proxy_filter.py`.

Prometheus query:
```
increase(osa_kali_socket_proxy_403_total[2m]) > 0
```

Dashboard: `OSA / Infra` panel "Network Membership Violations".

Audit log action: `infra.network_membership_violation`

## Likely causes

- Container started outside of docker-compose (missing network attachment).
- Docker network `osa_pentest_net` was recreated, invalidating existing container network memberships.
- Kali or attack container escaped expected network isolation.
- `OSA_NETWORK_MEMBERSHIP_CHECK=off` was accidentally removed from test env and check is now running in a non-containerised dev environment.
- Manual `docker network disconnect` run by operator without follow-up reconnect.

## Triage steps

1. Confirm violation in audit_logs:
   ```sql
   SELECT details_json, created_at, ip_address
   FROM audit_logs
   WHERE action = 'infra.network_membership_violation'
   ORDER BY created_at DESC LIMIT 10;
   ```
2. Inspect current container network state:
   ```bash
   docker inspect <backend_container_id> --format '{{json .NetworkSettings.Networks}}'
   docker network inspect osa_pentest_net
   ```
3. Verify all expected containers are present in `osa_pentest_net`:
   ```bash
   docker network inspect osa_pentest_net --format '{{range .Containers}}{{.Name}} {{end}}'
   ```
4. Check `/sys/class/net` interfaces inside the backend container:
   ```bash
   docker exec <backend_container> ls /sys/class/net
   ```
   Expected: at least one non-loopback interface on 172.x.x.x (RFC1918).
5. Review docker-compose for `osa_pentest_net` attachment on all services.

## Mitigation

- Immediate: Re-attach the backend container to `osa_pentest_net`:
  ```bash
  docker network connect osa_pentest_net <backend_container_id>
  ```
- If Kali container on wrong network: isolate immediately (`docker network disconnect <wrong_net> <kali_container>`).
- Full remediation: `docker-compose down && docker-compose up -d` to restore correct topology.

## Rollback

- Restore last-known-good docker-compose state from git.
- `docker-compose down --remove-orphans && docker-compose up -d`

## Related runbooks

- [[mitm-shim-block]]
- [[headless-shim-block]]
- [[oob-callback-received]]
- [[flag-tuple-replacement-table]]
