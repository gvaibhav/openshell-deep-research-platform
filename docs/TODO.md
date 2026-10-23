# Change request and ToDo index

This is the discovery index for design impacts. Each impact has a change request (CR) describing the required change and a paired ToDo containing executable tasks and evidence. The CR and ToDo carry the current matching **Status**; this index does not duplicate their acceptance criteria or status. The [design-change workflow](../AGENTS.md#design-change-impact-gate) requires a pair for every identified impact and direct links from the affected design and README. Keep pairs linked here after closure for audit.

The current source-authentication impacts come from [ADR 0001 and its impact analysis](decisions/0001-outbound-mcp-source-tokens.md#impact-analysis-and-document-disposition); the workflow impact comes from [ADR 0002](decisions/0002-design-impact-traceability.md#impact-analysis). The repository is still a design scaffold, so open and deferred component pairs below are obligations, not running controls.

| Impact | Implementable obligation | Change request | Paired ToDo | Phase or decision |
|---|---|---|---|---|
| DR-AUTH-001 | Version source-connection and API-to-broker handoff contracts | [CR-0001](change-requests/CR-0001-source-connection-contract.md) | [ToDo](todos/CR-0001-source-connection-contract.md) | Phase 1 contract gate |
| DR-AUTH-002 | Bind a source-authenticated user to the dashboard identity | [CR-0002](change-requests/CR-0002-source-identity-binding.md) | [ToDo](todos/CR-0002-source-identity-binding.md) | Phase 1 |
| DR-AUTH-003 | Build dashboard source-connection and reauthorization UX | [CR-0003](change-requests/CR-0003-source-connection-dashboard.md) | [ToDo](todos/CR-0003-source-connection-dashboard.md) | Phase 1 |
| DR-AUTH-004 | Build one approved read-only OAuth/MCP adapter | [CR-0004](change-requests/CR-0004-oauth-mcp-adapter.md) | [ToDo](todos/CR-0004-oauth-mcp-adapter.md) | Phase 1, one source at a time |
| DR-AUTH-005 | Vault, renew, revoke, and fence brokered source grants | [CR-0005](change-requests/CR-0005-grant-custody-revocation.md) | [ToDo](todos/CR-0005-grant-custody-revocation.md) | Phase 1 |
| DR-AUTH-006 | Qualify standard Okta OBO for a selected MCP | [CR-0006](change-requests/CR-0006-okta-standard-obo.md) | [ToDo](todos/CR-0006-okta-standard-obo.md) | Conditional source decision |
| DR-AUTH-007 | Qualify Okta for AI Agents STS/XAA | [CR-0007](change-requests/CR-0007-okta-ai-agents.md) | [ToDo](todos/CR-0007-okta-ai-agents.md) | Conditional source decision |
| DR-AUTH-008 | Qualify one direct OpenShell source connector | [CR-0008](change-requests/CR-0008-direct-openshell-source.md) | [ToDo](todos/CR-0008-direct-openshell-source.md) | Conditional Phase 2 |
| DR-PROC-001 | Enforce impact-to-implementation traceability and protected CI | [CR-0009](change-requests/CR-0009-design-impact-traceability.md) | [ToDo](todos/CR-0009-design-impact-traceability.md) | Local workflow now; CI before executable build |

A pair becomes **Verified** only when its required change and proof are recorded in both files and the design is reconciled. For an implementation impact, that means the named component or configuration change plus positive and negative evidence on pinned versions; documentation-only impacts need document review and checks. A deferred option stays visible until selected or explicitly **Withdrawn** with a decision that updates the intended design. Every implementation pull request links its pair and reports any new impact back into the analysis.
