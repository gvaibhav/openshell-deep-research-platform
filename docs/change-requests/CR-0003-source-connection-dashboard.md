# CR-0003: Show and manage source connections in the dashboard

- **ID:** CR-0003
- **Status:** Open
- **Impact ID:** DR-AUTH-003
- **Phase:** Phase 1
- **Accountable team:** Dashboard team with API team (proposed)
- **Component paths:** apps/dashboard/ and apps/api/
- **Requirement IDs:** CON-03, CON-14
- **Primary design:** [ADR 0001](../decisions/0001-outbound-mcp-source-tokens.md)
- **Detailed design:** [Dashboard boundary](../../apps/dashboard/README.md), [Job lifecycle](../design/job-lifecycle.md), [Broker connection design](../design/mcp-connector-broker.md#3-source-connection-and-consent)
- **Paired ToDo:** [Implementation checklist](../todos/CR-0003-source-connection-dashboard.md)

## Impact on the application

A researcher must know which source user or approved app will act, what resources and read scopes it can reach, and whether consent or renewal is needed before admitting a private job.

## Change request

Provide source-connection status, acting identity, resource and scope selection, consent/reauthorization, and disconnect through the BFF API. A long job requiring renewed user authority enters a trusted review state; the sandbox worker never starts browser OAuth.

## Required behavior

- **Accept:** The dashboard displays the verified acting identity and selected resources before job submission, and a current approved connection can be selected.
- **Deny:** Expired/revoked/mismatched connections, stale dashboard sessions, wrong user or tenant, unapproved app-only corpus, and forged consent callback cannot start a private job. Browser storage, events, and status contain no source token.

## Risk and disable path

- **Risk:** A misleading acting identity, stale connection status, or incomplete consent state can cause a researcher to submit a private job under the wrong source authority.
- **Disable path:** Disable protected-source selection and admission in both dashboard and API for the affected connection type until the displayed identity/status and server-side admission checks agree. Public-only research may continue.

## Dependency and closure gate

[CR-0001](CR-0001-source-connection-contract.md) and [CR-0002](CR-0002-source-identity-binding.md); approved UX and first connector metadata.

This repository is a design scaffold; this CR records work to be implemented and does not claim a running service or live conformance result. Close the CR only when its paired ToDo has the implementation pull request, versioned positive and negative evidence, and reconciled requirements, architecture, design, contracts, and component documentation. If this impact is withdrawn, record the reason and update both documents and the design links.
