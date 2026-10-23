# CR-0006: Qualify standard Okta OBO for a protected MCP

- **ID:** CR-0006
- **Status:** Deferred
- **Impact ID:** DR-AUTH-006
- **Phase:** Conditional Phase 1 or later; only if an Okta-protected MCP requires user OBO
- **Accountable team:** Connector broker team with Okta team (proposed)
- **Component paths:** services/connector-broker/, apps/api/, and Okta tenant configuration
- **Requirement IDs:** CON-15, OKTA-16, OKTA-17
- **Primary design:** [ADR 0001](../decisions/0001-outbound-mcp-source-tokens.md)
- **Detailed design:** [Okta source-flow handoff](../okta/requirements-and-design.md#6-outbound-source-token-choices-and-oktas-conditional-role), [Identity design](../design/identity-and-access.md#can-openshell-handle-the-token-flows)
- **Paired ToDo:** [Implementation checklist](../todos/CR-0006-okta-standard-obo.md)

## Impact on the application

Standard Okta OBO is a separate broker service-app exchange, not OpenShell SPIFFE exchange or reuse of the dashboard ID/org-server token. Its eligible user subject, actor claim, MCP resource, and long-job renewal must be proven in the live tenant.

## Change request

If selected, provision a separate confidential broker client and eligible custom-authorization-server user access-token source connection. Exchange only a verified same-person subject for the exact MCP target; preserve original-subject renewal or fail-closed reauthorization. Keep this mode disabled until entitlement, claims, and grant-specific resource behavior pass.

## Required behavior

- **Accept:** A nonproduction Okta tenant and MCP accept the correct user, broker client, exact resource, audience, read scopes, and source-owner-approved actor attribution or compatible audit alternative.
- **Deny:** Wrong user, subject type, issuer, client, resource, audience, scope, expired or unrenewable original grant, or revoked connection denies before a protected read. No refresh token is expected from the service-app exchange.

## Risk and disable path

- **Risk:** Standard OBO may issue a token for the wrong principal or MCP target, or an expired original user subject may silently remove user authority during a long job.
- **Disable path:** Keep OBO disabled until live tenant and source tests pass. If a selected OBO path fails, stop its source route and revoke its broker client/subject grant as appropriate. A separately qualified brokered Authorization Code user connection, or a source-approved app-only grant for a shared corpus, requires a new source-owner decision. OBO failure never enables direct OpenShell worker-to-source routing by itself.

## Dependency and closure gate

Source-owner and security selection; Okta NHI entitlement and production claim availability; [CR-0002](CR-0002-source-identity-binding.md), [CR-0004](CR-0004-oauth-mcp-adapter.md), and [CR-0005](CR-0005-grant-custody-revocation.md). Withdrawal or selection needs a recorded decision.

This repository is a design scaffold; this CR records work to be implemented and does not claim a running service or live conformance result. Close the CR only when its paired ToDo has the implementation pull request, versioned positive and negative evidence, and reconciled requirements, architecture, design, contracts, and component documentation. If this impact is withdrawn, record the reason and update both documents and the design links.
