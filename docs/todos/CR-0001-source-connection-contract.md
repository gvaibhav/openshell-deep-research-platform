# ToDo for CR-0001: Version the source-connection contract

- **ID:** CR-0001
- **Status:** Open
- **Impact ID:** DR-AUTH-001
- **Phase:** Phase 1; contract gate before connection code
- **Accountable team:** API contracts team (proposed)
- **Component paths:** contracts/openapi.yaml and contracts/
- **Requirement IDs:** CON-03, CON-07, CON-14
- **Change request:** [CR-0001](../change-requests/CR-0001-source-connection-contract.md)
- **Design baseline:** [ADR 0001](../decisions/0001-outbound-mcp-source-tokens.md)

## Implementation and proof checklist

- [ ] Choose the first protected source and record its source-owner-approved user or app identity and callback registration.
- [ ] Define browser start, callback, status, reauthorization, and disconnect requests, responses, and neutral errors in OpenAPI.
- [ ] Define the authenticated API-to-broker start/callback contract, one-use state, session binding, and broker-owned PKCE/code-exchange responsibilities.
- [ ] Add valid and denial fixtures; prove no source access or refresh token appears in browser responses, job payloads, or ordinary logs.
- [ ] Run contract validation and record the pull request, schema version, and allow/deny evidence.

## Completion evidence

- **Pull request and artifact versions:** Pending.
- **Allow/deny evidence:** Pending. Prove the paired [CR required behavior](../change-requests/CR-0001-source-connection-contract.md#required-behavior) with versioned test IDs and observed results, then link that evidence here.
- **Live qualification:** Pending; do not infer runtime behavior from make check.
- **Closure:** Reconcile implementation with the linked CR and affected design/contract documents. Mark both records Verified together only after the required proof passes; if withdrawn, mark both withdrawn with the source-owner or design decision.
