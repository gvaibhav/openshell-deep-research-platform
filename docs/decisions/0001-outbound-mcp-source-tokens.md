# ADR 0001: Outbound MCP source-token ownership and Okta options

- **Status:** Design decision for the candidate platform; source-by-source qualification remains open
- **Date:** 2026-10-23
- **Data class:** Public fixtures now; approved enterprise source data only after connector gates
- **Trust boundary:** Dashboard user → source connection → broker → protected MCP server; OpenShell worker → broker remains a separate hop
- **Affected requirements:** CON-03, CON-07, CON-08, CON-13–16, IAM-08; optional Okta handoff OKTA-16–18
- **Assumptions:** The custom service and first private connector pass the feasibility gate; the source owner approves its acting principal and read scope; the live issuer/MCP resource and renewal behavior remain unqualified until conformance testing.

## Decision

The resource broker remains the default outbound OAuth/MCP client and source-token custodian. OpenShell supplies a short-lived, attempt-bound credential to the worker-to-broker hop. The broker chooses a **user-delegated** source grant when the source must enforce an employee's permissions, or an **app-only** grant only for a source-owner-approved shared corpus whose native permissions fit the job. A direct OpenShell worker-to-source provider remains a separately qualified exception under the [direct connector gates](../design/mcp-connector-broker.md#6-direct-mcp-bypass-of-the-broker).

For an Okta-protected source MCP, ordinary Authorization Code or Client Credentials, standard Okta on-behalf-of (OBO), and Okta for AI Agents STS/XAA are **distinct, conditional integrations**. Streamable HTTP does not choose the grant. The broker must prove the source's canonical MCP `resource`, target binding, read scopes, source principal, renewal, and revocation against the actual issuer and server. Standard OBO needs a separate eligible user **access** token and broker service client; the dashboard org-server ID/access token is not a substitute, and the exchange supplies no refresh token. Okta for AI Agents has a separate subscription, agent-client, consent, custody, and revocation contract. OpenShell v0.1.5 provider token exchange is not assumed compatible with either flow. [Okta handoff](../okta/requirements-and-design.md#6-outbound-source-token-choices-and-oktas-conditional-role).

Before any user-delegated source grant is stored or used, the source connection service must verify the source-authenticated person and match that person to the dashboard session through an Okta/source-owner-approved **immutable, issuer-qualified account link**. The broker performs this check on the default path; a future direct OpenShell path needs equivalent proof before provider material is created. OAuth `state` and PKCE bind the transaction, but do not prove that both logins were performed by the same person. A dashboard session for user A followed by source authorization as user B is denied even if both users belong to one tenant.

The BFF Connection API owns the browser session and public callback. It forwards the one-use code, state, and verified session binding to the broker over an authenticated internal channel and receives no source token. The broker owns transaction state and PKCE verifier, source code exchange, grant-bound identity proof, same-person decision, connection record, and vault. An authenticated source-specific identity endpoint may provide a stable user ID when OIDC UserInfo or token introspection is unavailable; an app/bot principal cannot satisfy a user-grant identity check. The selected connector must prove its identity response belongs to the exchanged grant.

## Threat-model delta

| Threat | Required boundary and denial proof |
|---|---|
| Source-account mix-up or callback replay | BFF rechecks the live dashboard session; broker consumes state once, checks the stored user/tenant/session binding, and rejects A-dashboard/B-source identity before vaulting. |
| Source code or token leak through the API/worker | API-to-broker code relay is authenticated. The BFF processes the callback code without logging or application storage and redirects to a clean URL; the broker excludes codes and tokens from logs. Only the broker exchanges the code and stores source token/refresh material; API receives an opaque connection reference and display-safe metadata. |
| Token confused deputy | Broker uses the selected source's grant, canonical MCP `resource`, acting principal, read scope, and exact source selectors; a dashboard, gateway, or broker-audience token cannot pass as a source token. |
| Long-job renewal, disconnect, or restore race | Broker renewal preserves the original grant's user and scope, and source dispatch/return closes on revocation. The independent denial ledger and recovery-generation fence stop a restored old grant. |
| Direct-provider reuse or copied source token | Direct mode stays disabled until same-person proof for user grants, per-attempt provider lineage, upstream sender binding, and established-stream revocation/restore fencing pass live tests. |

## Impact analysis and document disposition

This matrix records which surfaces changed, where they were revised, and which tracked impacts own their remaining work. Every **Affected** row maps to at least one impact ID in the [impact register](#actionable-impact-register); a surface can share an impact with another surface. The document revisions are present now; the component obligations remain open or deferred until their proof gates pass.

| Surface | Disposition | Revision or reason | Mapped impact IDs |
|---|---|---|---|
| README and source-authentication navigation | **Affected** | [README](../../README.md#tracked-change-requests) and the [CR/ToDo index](../TODO.md) link every source-authentication pair. The separate [workflow decision](0002-design-impact-traceability.md) owns changes to the delivery process and reviewer checks. | DR-AUTH-001–008 |
| Numbered requirements | **Affected** | [Connector requirements](../requirements.md#54-connectors-mcp-and-source-grants) add source-user identity matching, conditional Okta exchange, MCP target binding, renewal, and denied cases. | DR-AUTH-001–008 |
| Architecture and detailed design | **Affected** | [Architecture](../architecture.md#3-trust-and-identity-boundaries), [identity and access](../design/identity-and-access.md#oauth-protected-mcp-design), and [broker design](../design/mcp-connector-broker.md) state the broker/direct boundary, per-source flow choice, and account-link proof. The [Okta handoff](../okta/requirements-and-design.md) supplies conditional tenant objects and acceptance evidence. | DR-AUTH-001–008 |
| Deployment, operations, and security gates | **Affected** | [Deployment gates](../design/deployment-and-operations.md#10-promotion-integration-gates) include the chosen grant's live nonproduction issuer/MCP tests, user-mismatch denial, resource/audience denial, renewal, and revocation. | DR-AUTH-002, 004–008 |
| Browser/API/broker/OpenShell guides and application logic | **Affected** | [Dashboard](../../apps/dashboard/README.md), [API](../../apps/api/README.md), [broker](../../services/connector-broker/README.md), and [OpenShell notes](../../infra/openshell/README.md) describe their planned responsibilities. No executable service exists yet; the linked CR/ToDo pairs own each component obligation. | DR-AUTH-001–008 |
| Existing job JSON Schemas and OpenAPI operations | **Not affected** | The `connection_ref` in [source selection](../../contracts/source-selection.schema.json) and [job policy](../../contracts/job-policy.schema.json) already fits the decision; no existing payload or operation changes. | None |
| New source-connection and internal handoff contracts | **Affected; pending before code** | Browser start/callback/status/reauthorization/disconnect operations and authenticated API-to-broker messages are absent from [OpenAPI](../../contracts/openapi.yaml). The revised [contract notes](../../contracts/README.md) and [CR-0001](../change-requests/CR-0001-source-connection-contract.md) require the versioned contract before the first protected connector or dashboard flow is implemented. | DR-AUTH-001 |
| Existing examples and fixtures | **Not affected** | Current examples use opaque connection references and contain no OAuth token payload; no migration is needed. | None |
| New source-connection and grant proof fixtures | **Affected; pending before code** | New valid and denial fixtures for the connection, account binding, source grant, renewal, and optional flows are required when their contracts and adapters are built. The [paired ToDo for CR-0001](../todos/CR-0001-source-connection-contract.md) starts the fixture set. | DR-AUTH-001, 002, 004–008 |
| Tests and release gates | **Affected** | [Requirements Phase 1](../requirements.md#phase-1-read-only-enterprise-connectors), [broker conformance](../design/mcp-connector-broker.md#8-connector-conformance-gates), and [deployment promotion](../design/deployment-and-operations.md#10-promotion-integration-gates) add same-person, grant, audience, renewal, and revocation proof. Each pair below records its proof; no live test has run. | DR-AUTH-001–008 |
| Runtime OpenShell direct path | **Affected** | The direct path stays separately gated. A user-delegated direct grant must pass the same-person source identity check before its provider is created, alongside the existing [direct connector gates](../design/mcp-connector-broker.md#6-direct-mcp-bypass-of-the-broker) and [OpenShell guide](../../infra/openshell/README.md). | DR-AUTH-008 |
| Result visibility | **Not affected** | [Research visibility](../design/research-visibility.md) still requires each viewer's current source/classification rights; this decision does not widen a job audience. | None |

## Actionable impact register

Each row is one independently verifiable impact from this decision. Its CR captures the design-to-application change; its ToDo owns implementation tasks and evidence. The [README](../../README.md#tracked-change-requests) and [index](../TODO.md) link the same pairs through and after closure for audit. A pair is `Verified` only with its required implementation and proof, or `Withdrawn` with a recorded design decision.

| Impact | Required change | Change request | Paired ToDo |
|---|---|---|---|
| DR-AUTH-001 | Source-connection and internal handoff contract | [CR-0001](../change-requests/CR-0001-source-connection-contract.md) | [ToDo](../todos/CR-0001-source-connection-contract.md) |
| DR-AUTH-002 | Same-person source identity binding | [CR-0002](../change-requests/CR-0002-source-identity-binding.md) | [ToDo](../todos/CR-0002-source-identity-binding.md) |
| DR-AUTH-003 | Dashboard source-connection UX | [CR-0003](../change-requests/CR-0003-source-connection-dashboard.md) | [ToDo](../todos/CR-0003-source-connection-dashboard.md) |
| DR-AUTH-004 | Read-only OAuth/MCP adapter | [CR-0004](../change-requests/CR-0004-oauth-mcp-adapter.md) | [ToDo](../todos/CR-0004-oauth-mcp-adapter.md) |
| DR-AUTH-005 | Grant custody, renewal, and revocation | [CR-0005](../change-requests/CR-0005-grant-custody-revocation.md) | [ToDo](../todos/CR-0005-grant-custody-revocation.md) |
| DR-AUTH-006 | Conditional standard Okta OBO | [CR-0006](../change-requests/CR-0006-okta-standard-obo.md) | [ToDo](../todos/CR-0006-okta-standard-obo.md) |
| DR-AUTH-007 | Conditional Okta for AI Agents | [CR-0007](../change-requests/CR-0007-okta-ai-agents.md) | [ToDo](../todos/CR-0007-okta-ai-agents.md) |
| DR-AUTH-008 | Conditional direct OpenShell source access | [CR-0008](../change-requests/CR-0008-direct-openshell-source.md) | [ToDo](../todos/CR-0008-direct-openshell-source.md) |

## Required proof before a protected connector is enabled

Use the selected source owner and a nonproduction issuer/server to prove: A-dashboard/B-source mismatch denial before vaulting; a valid same-user connection; exact MCP resource and read-scope acceptance; wrong-resource, wrong-principal, unsupported-grant, expired-subject, and revoked-connection denial; renewal or explicit reauthorization over a long-running job; and source-call fencing after disconnect. Standard OBO additionally needs tenant entitlement, an eligible custom-server subject token, actor attribution or an accepted resource-policy-compatible audit alternative, and a successful MCP `resource` token request. The separately licensed AI Agents path needs its own consent/agent-client and full external-grant revocation tests. The [CR/ToDo pairs](#actionable-impact-register) name the components and acceptance work; this ADR does not claim those tests have run.
