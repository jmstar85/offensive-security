# Flag Tuple Replacement Table

Per MF-CRITIC-8 — pairwise prerequisite matrix replacing the unstructured 7-tuple list.

## Prerequisite Matrix

| If you enable this flag | Then these flags MUST be ON | And these flags MUST be OFF |
|-------------------------|------------------------------|------------------------------|
| `osa_xbow_families_enabled` | `osa_coordinator_enabled`, `osa_multi_provider_llm` | (none) |
| `osa_traffic_via_mitm` | `osa_mitm_proxy_enabled`, `osa_xbow_families_enabled`, `osa_coordinator_enabled`, `osa_multi_provider_llm` | (none) |
| `osa_mitm_proxy_enabled` | `osa_multi_provider_llm` | (none) |
| `osa_headless_browser_enabled` | `osa_multi_provider_llm` | (none) |
| `osa_collaborator_enabled` | `osa_multi_provider_llm` | (none) |
| `osa_coordinator_enabled` | `osa_multi_provider_llm` | (none) |
| `osa_multi_provider_llm` | (none) | (none) |

Enforced by `validate_flag_topology` in `app/core/feature_flag_validator.py`. Violations in `environment=production` raise `UnsupportedFlagTopology`.

## Tuple Transitions

The four supported tuples and their flag values:

| Tuple | `osa_multi_provider_llm` | `osa_coordinator_enabled` | `osa_xbow_families_enabled` | `osa_mitm_proxy_enabled` | `osa_headless_browser_enabled` | `osa_collaborator_enabled` | `osa_traffic_via_mitm` |
|-------|--------------------------|---------------------------|-----------------------------|--------------------------|-------------------------------|---------------------------|------------------------|
| **T1** | False | False | False | False | False | False | False |
| **T2** | True | False | False | False | False | False | False |
| **T3** | True | True | True | False | False | False | False |
| **T4** | True | True | True | True | True | True | True |

### Transition Order

T1 → T2 → T3 → T4

Rollout percentages per PR5.4:
- T1 → T2: 10% of traffic
- T2 → T3: 50% of traffic
- T3 → T4: 100% of traffic

Never skip tuples (e.g. T1 → T4 directly). Each step must be validated for 24h before advancing.

### Reverse Rollback Ordering

T4 → T3 → T2 → T1, each within 10-minute SLA.

Rollback procedure for each step:
1. Identify the flags added in the forward transition.
2. Set those flags to `False` in `.env`.
3. Restart the backend service within 10 minutes.
4. Verify via `GET /api/v1/feature-flags` that the prior tuple is restored.
5. Monitor `osa_domain_agent_dispatch_total` for errors for 5 minutes.

## Related runbooks

- [[unsupported-flag-topology]]
- [[coordinator-iteration-cap]]
- [[mitm-shim-block]]
- [[headless-shim-block]]
