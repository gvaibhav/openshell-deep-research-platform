# ToDo for CR-0006: Qualify standard Okta OBO for a protected MCP

- **ID:** CR-0006
- **Status:** Deferred
- **Impact ID:** DR-AUTH-006
- **Phase:** Conditional Phase 1 or later; only if an Okta-protected MCP requires user OBO
- **Accountable team:** Connector broker team with Okta team (proposed)
- **Component paths:** services/connector-broker/, apps/api/, and Okta tenant configuration
- **Requirement IDs:** CON-15, OKTA-16, OKTA-17
- **Change request:** [CR-0006](../change-requests/CR-0006-okta-standard-obo.md)
- **Design baseline:** [ADR 0001](../decisions/0001-outbound-mcp-source-tokens.md)

## Implementation and proof checklist

- [ ] Record the source-specific enable-or-withdraw decision with source owner and security; keep OBO disabled while Deferred.
- [ ] Confirm Okta entitlement, eligible custom-server user access-token subject, trusted target server, and separate broker confidential client.
- [ ] Implement exact MCP resource/audience/scopes exchange and inspect user subject and actor claim or approved compatible audit fallback.
- [ ] Renew the original source user grant or pause for reauthorization; never treat an OBO response as a refresh grant.
- [ ] Run live positive and wrong-user/subject-type/issuer/client/resource/scope/expiry/revocation denial tests before activation.

## Completion evidence

- **Pull request and artifact versions:** Pending.
- **Allow/deny evidence:** Pending. Prove the paired [CR required behavior](../change-requests/CR-0006-okta-standard-obo.md#required-behavior) with versioned test IDs and observed results, then link that evidence here.
- **Live qualification:** Pending; do not infer runtime behavior from make check.
- **Closure:** Reconcile implementation with the linked CR and affected design/contract documents. Mark both records Verified together only after the required proof passes; if withdrawn, mark both withdrawn with the source-owner or design decision.
