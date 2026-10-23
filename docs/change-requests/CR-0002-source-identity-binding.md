# CR-0002: Bind a source login to the dashboard person

- **ID:** CR-0002
- **Status:** Open
- **Impact ID:** DR-AUTH-002
- **Phase:** Phase 1
- **Accountable team:** Connector broker team with API team (proposed)
- **Component paths:** apps/api/ and services/connector-broker/
- **Requirement IDs:** CON-14
- **Primary design:** [ADR 0001](../decisions/0001-outbound-mcp-source-tokens.md)
- **Detailed design:** [Identity design](../design/identity-and-access.md#oauth-protected-mcp-design), [Broker connection design](../design/mcp-connector-broker.md#3-source-connection-and-consent), [Okta source-flow handoff](../okta/requirements-and-design.md#6-outbound-source-token-choices-and-oktas-conditional-role)
- **Paired ToDo:** [Implementation checklist](../todos/CR-0002-source-identity-binding.md)

## Impact on the application

OAuth state and PKCE bind a transaction but do not prove the source login was performed by the dashboard user. The BFF callback and broker exchange/identity/vault split requires one explicit same-person decision before a connection becomes usable.

## Change request

Implement the BFF callback facade and authenticated code relay. The broker owns one-use state, PKCE verifier, code exchange, grant-bound source identity proof, immutable issuer-qualified dashboard/source account mapping, connection record, and vault. Store a user grant only after the account match.

## Required behavior

- **Accept:** A same-person source login produces an active opaque connection for the verified dashboard issuer, subject, and tenant; only identity references reach audit.
- **Deny:** Dashboard A with source B denies before vaulting or research dispatch even within one tenant. Replayed state, bot/app identity on a user path, cross-issuer or email-only matches, unknown mapping, and cross-tenant links deny. A mismatched transient token is discarded and revoked where supported; the API never receives source tokens.

## Risk and disable path

- **Risk:** A valid OAuth transaction may link dashboard user A to source user B, giving A access through B source authority.
- **Disable path:** Disable new user-delegated connections and protected reads for the affected source, discard transient grants, and revoke any suspect stored source grants. Reopen only after same-person proof and denial tests pass.

## Dependency and closure gate

[CR-0001](CR-0001-source-connection-contract.md); an approved source identity endpoint or claim bound to the grant; an Okta/source-owner-approved stable account mapping.

This repository is a design scaffold; this CR records work to be implemented and does not claim a running service or live conformance result. Close the CR only when its paired ToDo has the implementation pull request, versioned positive and negative evidence, and reconciled requirements, architecture, design, contracts, and component documentation. If this impact is withdrawn, record the reason and update both documents and the design links.
