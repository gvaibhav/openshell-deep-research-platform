# ToDo for CR-0007: Evaluate Okta for AI Agents STS or XAA

- **ID:** CR-0007
- **Status:** Deferred
- **Impact ID:** DR-AUTH-007
- **Phase:** Future conditional source-specific decision
- **Accountable team:** Connector broker team with Okta team (proposed)
- **Component paths:** services/connector-broker/, apps/api/, apps/dashboard/, and Okta tenant configuration
- **Requirement IDs:** CON-16, OKTA-18
- **Change request:** [CR-0007](../change-requests/CR-0007-okta-ai-agents.md)
- **Design baseline:** [ADR 0001](../decisions/0001-outbound-mcp-source-tokens.md)

## Implementation and proof checklist

- [ ] Record the source-specific enable-or-withdraw decision, subscription, owner approval, and separate architecture review; keep this mode disabled while Deferred.
- [ ] Specify agent-client subject/delegation, target resource, Okta-held and source-held grant custody, and interaction_required browser completion.
- [ ] Implement and test controlled consent, target binding, expiry/renewal, and full source-owner disconnect/revocation.
- [ ] Retain broker job-level tool, argument, response, provenance, and revocation checks or prove an independently reviewed equivalent.
- [ ] Run live positive and wrong-client-ID-token, wrong-user, wrong-resource, missing-consent, expiry, and partial-revocation denial tests.

## Completion evidence

- **Pull request and artifact versions:** Pending.
- **Allow/deny evidence:** Pending. Prove the paired [CR required behavior](../change-requests/CR-0007-okta-ai-agents.md#required-behavior) with versioned test IDs and observed results, then link that evidence here.
- **Live qualification:** Pending; do not infer runtime behavior from make check.
- **Closure:** Reconcile implementation with the linked CR and affected design/contract documents. Mark both records Verified together only after the required proof passes; if withdrawn, mark both withdrawn with the source-owner or design decision.
