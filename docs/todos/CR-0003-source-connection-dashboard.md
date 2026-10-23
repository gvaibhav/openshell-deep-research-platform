# ToDo for CR-0003: Show and manage source connections in the dashboard

- **ID:** CR-0003
- **Status:** Open
- **Impact ID:** DR-AUTH-003
- **Phase:** Phase 1
- **Accountable team:** Dashboard team with API team (proposed)
- **Component paths:** apps/dashboard/ and apps/api/
- **Requirement IDs:** CON-03, CON-14
- **Change request:** [CR-0003](../change-requests/CR-0003-source-connection-dashboard.md)
- **Design baseline:** [ADR 0001](../decisions/0001-outbound-mcp-source-tokens.md)

## Implementation and proof checklist

- [ ] Design status and selection states for connected, consent pending, expired, revoked, reauthorization required, and disconnected sources.
- [ ] Display the broker-verified acting user or app, approved resource set, read scopes, and connection status before submission.
- [ ] Wire consent, reauthorization, and disconnect through token-free BFF operations; keep worker and browser away from source token material.
- [ ] Gate job submission on current connection and resource selection; render neutral denial and partial-job reauthorization states.
- [ ] Test authorized selection and wrong-user, wrong-tenant, expired, revoked, unapproved app-only, stale-session, and forged-callback denial.

## Completion evidence

- **Pull request and artifact versions:** Pending.
- **Allow/deny evidence:** Pending. Prove the paired [CR required behavior](../change-requests/CR-0003-source-connection-dashboard.md#required-behavior) with versioned test IDs and observed results, then link that evidence here.
- **Live qualification:** Pending; do not infer runtime behavior from make check.
- **Closure:** Reconcile implementation with the linked CR and affected design/contract documents. Mark both records Verified together only after the required proof passes; if withdrawn, mark both withdrawn with the source-owner or design decision.
