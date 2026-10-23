# CR-0004: Implement one read-only OAuth or MCP source adapter

- **ID:** CR-0004
- **Status:** Open
- **Impact ID:** DR-AUTH-004
- **Phase:** Phase 1; one source at a time
- **Accountable team:** Connector broker team (proposed)
- **Component paths:** services/connector-broker/
- **Requirement IDs:** CON-01, CON-02, CON-03, CON-07, CON-08, CON-09
- **Primary design:** [ADR 0001](../decisions/0001-outbound-mcp-source-tokens.md)
- **Detailed design:** [Connector conformance gates](../design/mcp-connector-broker.md#8-connector-conformance-gates), [Okta source-flow handoff](../okta/requirements-and-design.md#6-outbound-source-token-choices-and-oktas-conditional-role)
- **Paired ToDo:** [Implementation checklist](../todos/CR-0004-oauth-mcp-adapter.md)

## Impact on the application

An OAuth-protected MCP cannot be safely reached through a generic bearer passthrough. The source needs a reviewed grant, exact canonical MCP resource and audience, native permission model, read-tool and argument policy, and verified response scope.

## Change request

Build one source-specific broker adapter with protected-resource discovery, issuer/client registration, supported grant, resource-indicator behavior, Streamable HTTP transport, exact read scopes, tool/argument/response validation, and trusted provenance. Use app-only credentials only for a source-owner-approved shared corpus whose native app RBAC matches the job.

## Required behavior

- **Accept:** A real nonproduction issuer and server accept an authorized read for the exact source principal and selected resource, with bounded attributed results.
- **Deny:** Wrong resource, audience, issuer, client, scope, principal, tenant, selector, out-of-scope returned item, or write tool denies before dispatch or worker delivery. A service token does not inherit a submitter private ACL.

## Risk and disable path

- **Risk:** A generic or misconfigured adapter may send the wrong token, widen a source query, admit a write tool, or release an out-of-scope result.
- **Disable path:** Disable that connector registration and its broker tool route; revoke or rotate its source credential when needed. Keep other qualified source routes independent and require a new nonproduction conformance run before re-enabling.

## Dependency and closure gate

Source-owner contract and MCP version pin; [CR-0001](CR-0001-source-connection-contract.md) and [CR-0002](CR-0002-source-identity-binding.md) for user grants; coordinate token custody and revocation with [CR-0005](CR-0005-grant-custody-revocation.md).

This repository is a design scaffold; this CR records work to be implemented and does not claim a running service or live conformance result. Close the CR only when its paired ToDo has the implementation pull request, versioned positive and negative evidence, and reconciled requirements, architecture, design, contracts, and component documentation. If this impact is withdrawn, record the reason and update both documents and the design links.
