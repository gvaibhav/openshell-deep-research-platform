# ToDo for CR-0002: Bind a source login to the dashboard person

- **ID:** CR-0002
- **Status:** Open
- **Impact ID:** DR-AUTH-002
- **Phase:** Phase 1
- **Accountable team:** Connector broker team with API team (proposed)
- **Component paths:** apps/api/ and services/connector-broker/
- **Requirement IDs:** CON-14
- **Change request:** [CR-0002](../change-requests/CR-0002-source-identity-binding.md)
- **Design baseline:** [ADR 0001](../decisions/0001-outbound-mcp-source-tokens.md)

## Implementation and proof checklist

- [ ] Implement the BFF source callback with current-session and CSRF checks and authenticated code/state/session relay to the broker.
- [ ] Implement broker-owned one-use transaction state, S256 PKCE, code exchange, and stable source user identity proof bound to the exchanged grant.
- [ ] Resolve the immutable issuer-qualified dashboard-to-source account link and vault only after an exact verified match.
- [ ] Discard a mismatched transient token and invoke source revocation when supported; exclude codes and tokens from ordinary logs and API responses.
- [ ] Test same-person success and A-dashboard/B-source, replay, bot/app, email-only, cross-issuer, unknown-link, and cross-tenant denial.

## Completion evidence

- **Pull request and artifact versions:** Pending.
- **Allow/deny evidence:** Pending. Prove the paired [CR required behavior](../change-requests/CR-0002-source-identity-binding.md#required-behavior) with versioned test IDs and observed results, then link that evidence here.
- **Live qualification:** Pending; do not infer runtime behavior from make check.
- **Closure:** Reconcile implementation with the linked CR and affected design/contract documents. Mark both records Verified together only after the required proof passes; if withdrawn, mark both withdrawn with the source-owner or design decision.
