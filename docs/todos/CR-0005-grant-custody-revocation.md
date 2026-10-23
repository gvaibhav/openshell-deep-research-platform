# ToDo for CR-0005: Vault and fence brokered source grants

- **ID:** CR-0005
- **Status:** Open
- **Impact ID:** DR-AUTH-005
- **Phase:** Phase 1
- **Accountable team:** Connector broker team with API team (proposed)
- **Component paths:** services/connector-broker/ and apps/api/
- **Requirement IDs:** IAM-08, CON-03
- **Change request:** [CR-0005](../change-requests/CR-0005-grant-custody-revocation.md)
- **Design baseline:** [ADR 0001](../decisions/0001-outbound-mcp-source-tokens.md)

## Implementation and proof checklist

- [ ] Implement encrypted per-tenant/source grant custody, expiry, rotation, and renewal limited to the original approved user and scopes.
- [ ] Add trusted reauthorization pause when renewal cannot preserve authority; never ask a sandbox worker to complete browser OAuth.
- [ ] Write the source-connection denial tombstone before acknowledgement and fence new and in-flight dispatch/return across replicas.
- [ ] Reconcile restore against the independent ledger head and external recovery generation before reopening source access.
- [ ] Prove long-job renewal and race denial at pre-dispatch, buffered response, established stream, crashed replica, and pre-revocation backup restore.

## Completion evidence

- **Pull request and artifact versions:** Pending.
- **Allow/deny evidence:** Pending. Prove the paired [CR required behavior](../change-requests/CR-0005-grant-custody-revocation.md#required-behavior) with versioned test IDs and observed results, then link that evidence here.
- **Live qualification:** Pending; do not infer runtime behavior from make check.
- **Closure:** Reconcile implementation with the linked CR and affected design/contract documents. Mark both records Verified together only after the required proof passes; if withdrawn, mark both withdrawn with the source-owner or design decision.
