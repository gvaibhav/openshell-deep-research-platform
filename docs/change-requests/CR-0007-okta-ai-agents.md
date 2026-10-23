# CR-0007: Evaluate Okta for AI Agents STS or XAA

- **ID:** CR-0007
- **Status:** Deferred
- **Impact ID:** DR-AUTH-007
- **Phase:** Future conditional source-specific decision
- **Accountable team:** Connector broker team with Okta team (proposed)
- **Component paths:** services/connector-broker/, apps/api/, apps/dashboard/, and Okta tenant configuration
- **Requirement IDs:** CON-16, OKTA-18
- **Primary design:** [ADR 0001](../decisions/0001-outbound-mcp-source-tokens.md)
- **Detailed design:** [Okta source-flow handoff](../okta/requirements-and-design.md#6-outbound-source-token-choices-and-oktas-conditional-role), [Broker connector design](../design/mcp-connector-broker.md)
- **Paired ToDo:** [Implementation checklist](../todos/CR-0007-okta-ai-agents.md)

## Impact on the application

Okta for AI Agents uses a separately registered agent/resource connection and consent or machine delegation. It changes subject-token, target-binding, refresh custody, and disconnect semantics; one short-lived STS token revocation is not a complete source disconnect.

## Change request

If selected, design STS for an external source or XAA/ID-JAG for an Okta-protected MCP as a separate integration. Preserve broker job-level tool/argument/evidence checks unless an independently qualified replacement proves equivalence. Define interactive consent, grant custody, renewal, and full external-source disconnect.

## Required behavior

- **Accept:** A live registered agent client and source prove correct user or approved machine delegation, target resource, consent handling including interaction_required, and complete underlying grant disconnect.
- **Deny:** A dashboard-client ID token, another user grant, wrong resource, missing consent, expired authority, or revocation of only one STS token cannot authorize a protected read or count as disconnect.

## Risk and disable path

- **Risk:** An AI Agents STS/XAA token may outlive or obscure the underlying source connection, leaving access after an incomplete disconnect.
- **Disable path:** Keep STS/XAA disabled until full consent, custody, and source-grant revocation are proven. On failure, close the integration and revoke Okta-held and external source grants under the source-owner procedure.

## Dependency and closure gate

Subscription, registered agent/resource connection, source-owner and security decision, separate architecture review, [CR-0001](CR-0001-source-connection-contract.md)/0002/0004/0005. Withdrawal or selection needs a recorded decision.

This repository is a design scaffold; this CR records work to be implemented and does not claim a running service or live conformance result. Close the CR only when its paired ToDo has the implementation pull request, versioned positive and negative evidence, and reconciled requirements, architecture, design, contracts, and component documentation. If this impact is withdrawn, record the reason and update both documents and the design links.
