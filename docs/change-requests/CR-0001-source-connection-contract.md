# CR-0001: Version the source-connection contract

- **ID:** CR-0001
- **Status:** Open
- **Impact ID:** DR-AUTH-001
- **Phase:** Phase 1; contract gate before connection code
- **Accountable team:** API contracts team (proposed)
- **Component paths:** contracts/openapi.yaml and contracts/
- **Requirement IDs:** CON-03, CON-07, CON-14
- **Primary design:** [ADR 0001](../decisions/0001-outbound-mcp-source-tokens.md)
- **Detailed design:** [Broker connection design](../design/mcp-connector-broker.md#3-source-connection-and-consent), [Okta source-flow handoff](../okta/requirements-and-design.md#6-outbound-source-token-choices-and-oktas-conditional-role)
- **Paired ToDo:** [Implementation checklist](../todos/CR-0001-source-connection-contract.md)

## Impact on the application

The present job contract carries an opaque connection reference, but it does not define browser source-connection operations or the authenticated API-to-broker callback handoff. Implementation against an implicit contract would let token custody and same-person checks drift between services.

## Change request

Specify versioned start, callback, status, reauthorization, and disconnect operations. Define the internal start/callback messages so the API relays a one-use authorization code, state, and verified session binding; the broker holds PKCE, exchanges the code, and returns only an opaque reference and display-safe metadata.

## Required behavior

- **Accept:** A valid same-session connection follows the contract, produces only an opaque connection ID and display-safe source identity/resource metadata, and validates against the versioned schema.
- **Deny:** Forged or replayed callback state, cross-tenant connection IDs, missing mutation CSRF, stale session binding, and token fields in browser responses are rejected. The callback code is removed from the browser URL after processing.

## Risk and disable path

- **Risk:** An incomplete contract can let API and broker implementations disagree on callback/session binding or accidentally return source credentials to the browser.
- **Disable path:** Do not enable a protected source connection until the versioned public and internal contracts, examples, and denial tests are accepted. Keep the affected connection endpoints and private connector disabled if contract conformance fails.

## Dependency and closure gate

Select the first source, acting user/app identity, and callback/identity method with its owner. Complete this contract before [CR-0002](CR-0002-source-identity-binding.md) or [CR-0003](CR-0003-source-connection-dashboard.md) implementation.

This repository is a design scaffold; this CR records work to be implemented and does not claim a running service or live conformance result. Close the CR only when its paired ToDo has the implementation pull request, versioned positive and negative evidence, and reconciled requirements, architecture, design, contracts, and component documentation. If this impact is withdrawn, record the reason and update both documents and the design links.
