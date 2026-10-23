# ToDo for CR-0004: Implement one read-only OAuth or MCP source adapter

- **ID:** CR-0004
- **Status:** Open
- **Impact ID:** DR-AUTH-004
- **Phase:** Phase 1; one source at a time
- **Accountable team:** Connector broker team (proposed)
- **Component paths:** services/connector-broker/
- **Requirement IDs:** CON-01, CON-02, CON-03, CON-07, CON-08, CON-09
- **Change request:** [CR-0004](../change-requests/CR-0004-oauth-mcp-adapter.md)
- **Design baseline:** [ADR 0001](../decisions/0001-outbound-mcp-source-tokens.md)

## Implementation and proof checklist

- [ ] Select one approved source and pin issuer, MCP server/protocol, client registration method, principal, scopes, and canonical resource.
- [ ] Implement grant-specific token acquisition and Streamable HTTP requests with target resource and audience validation.
- [ ] Expose only typed read tools; enforce exact argument, resource, time, size, and per-item response scope before worker release.
- [ ] Integrate trusted provenance and broker authorization against the current job/source policy.
- [ ] Run live nonproduction allow/deny tests for resource, audience, issuer, client, scope, identity, selector, returned item, and write-tool cases.

## Completion evidence

- **Pull request and artifact versions:** Pending.
- **Allow/deny evidence:** Pending. Prove the paired [CR required behavior](../change-requests/CR-0004-oauth-mcp-adapter.md#required-behavior) with versioned test IDs and observed results, then link that evidence here.
- **Live qualification:** Pending; do not infer runtime behavior from make check.
- **Closure:** Reconcile implementation with the linked CR and affected design/contract documents. Mark both records Verified together only after the required proof passes; if withdrawn, mark both withdrawn with the source-owner or design decision.
