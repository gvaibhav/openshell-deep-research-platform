# CR-0008: Qualify one direct OpenShell source connector

- **ID:** CR-0008
- **Status:** Deferred
- **Impact ID:** DR-AUTH-008
- **Phase:** Conditional Phase 2; after brokered source path
- **Accountable team:** OpenShell integration team (proposed)
- **Component paths:** infra/openshell/, services/controller/, and apps/worker/
- **Requirement IDs:** CON-13, IAM-08; CON-14 for a user grant
- **Primary design:** [ADR 0001](../decisions/0001-outbound-mcp-source-tokens.md)
- **Detailed design:** [Direct connector design](../design/mcp-connector-broker.md#6-direct-mcp-bypass-of-the-broker), [OpenShell integration](../../infra/openshell/README.md)
- **Paired ToDo:** [Implementation checklist](../todos/CR-0008-direct-openshell-source.md)

## Impact on the application

Direct worker-to-source tokens move source credential custody and response delivery into the OpenShell path. This bypasses broker argument/response gates and creates separate raw-token replay, provider reuse, classification, revocation, and restore risks.

## Change request

Only after proving value over the brokered path, qualify one connector with exact per-attempt provider and grant lineage, canonical MCP resource, upstream partition RBAC and sender binding, pre-ready mint/egress barrier, trusted evidence/class-before-worker path, and live/restore stream fencing. A user grant must pass same-person source identity proof before provider material exists.

## Required behavior

- **Accept:** On one pinned live OpenShell runtime, an approved narrow source call succeeds under the exact job/stage/attempt and source resource while trusted provenance and class handling remain intact.
- **Deny:** Pre-ready source call or mint, copied raw vendor token, reuse in another attempt, broader attached-provider update, wrong MCP resource, over-class response, and post-revocation or post-restore established stream all deny. Failure keeps direct mode disabled.

## Risk and disable path

- **Risk:** A direct provider may leak a replayable source token or bypass broker response, classification, revocation, and restore controls.
- **Disable path:** Keep direct mode disabled until all live gates pass. On failure, close source egress and token minting, quarantine or delete old direct sandboxes, revoke upstream tokens, and return to the independently qualified broker path.

## Dependency and closure gate

A working brokered baseline, source-owner and security approval, issuer/upstream sender-binding proof, pinned runtime/CNI, and live revocation/restore gates. Withdrawal or selection needs a recorded decision.

This repository is a design scaffold; this CR records work to be implemented and does not claim a running service or live conformance result. Close the CR only when its paired ToDo has the implementation pull request, versioned positive and negative evidence, and reconciled requirements, architecture, design, contracts, and component documentation. If this impact is withdrawn, record the reason and update both documents and the design links.
