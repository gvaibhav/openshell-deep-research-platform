# ToDo for CR-0008: Qualify one direct OpenShell source connector

- **ID:** CR-0008
- **Status:** Deferred
- **Impact ID:** DR-AUTH-008
- **Phase:** Conditional Phase 2; after brokered source path
- **Accountable team:** OpenShell integration team (proposed)
- **Component paths:** infra/openshell/, services/controller/, and apps/worker/
- **Requirement IDs:** CON-13, IAM-08; CON-14 for a user grant
- **Change request:** [CR-0008](../change-requests/CR-0008-direct-openshell-source.md)
- **Design baseline:** [ADR 0001](../decisions/0001-outbound-mcp-source-tokens.md)

## Implementation and proof checklist

- [ ] Record the measured benefit and source-specific enable-or-withdraw decision; keep direct mode disabled while Deferred.
- [ ] Verify user same-person proof before provider creation when a user grant is proposed; otherwise obtain source-owner approval for app-only shared access.
- [ ] Bind provider instance, profile digest, credential generation, sandbox, and attempt; deny external provider updates and cross-attempt grant reuse.
- [ ] Prove upstream raw-token sender binding and pre-ready token-mint/source-egress barriers on the pinned runtime and CNI.
- [ ] Prove trusted evidence and class-before-worker/model handling, plus disconnect/restore fencing of established streams and cached tokens.
- [ ] Run the complete direct-mode positive and denial matrix and retain exact runtime/policy/provider evidence before activation.

## Completion evidence

- **Pull request and artifact versions:** Pending.
- **Allow/deny evidence:** Pending. Prove the paired [CR required behavior](../change-requests/CR-0008-direct-openshell-source.md#required-behavior) with versioned test IDs and observed results, then link that evidence here.
- **Live qualification:** Pending; do not infer runtime behavior from make check.
- **Closure:** Reconcile implementation with the linked CR and affected design/contract documents. Mark both records Verified together only after the required proof passes; if withdrawn, mark both withdrawn with the source-owner or design decision.
