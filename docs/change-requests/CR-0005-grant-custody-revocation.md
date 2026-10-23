# CR-0005: Vault and fence brokered source grants

- **ID:** CR-0005
- **Status:** Open
- **Impact ID:** DR-AUTH-005
- **Phase:** Phase 1
- **Accountable team:** Connector broker team with API team (proposed)
- **Component paths:** services/connector-broker/ and apps/api/
- **Requirement IDs:** IAM-08, CON-03
- **Primary design:** [ADR 0001](../decisions/0001-outbound-mcp-source-tokens.md)
- **Detailed design:** [Broker revocation](../design/mcp-connector-broker.md#7-connection-state-failures-and-revocation), [Restore design](../design/deployment-and-operations.md#7-backups-retention-and-restore)
- **Paired ToDo:** [Implementation checklist](../todos/CR-0005-grant-custody-revocation.md)

## Impact on the application

Long research jobs need source-grant renewal without broader authority, while disconnect, cancellation, crash, and restore must stop both source dispatch and worker-visible return after acknowledgement.

## Change request

Keep brokered source grants and refresh material in an encrypted tenant/source vault. Implement approved renewal, reauthorization pause, an independent durable denial ledger, active-call/stream fencing across replicas, and recovery-generation checks. An OBO exchange does not renew its original user subject grant.

## Required behavior

- **Accept:** A long approved job renews the original grant without scope growth or pauses for reauthorization. A current valid connection permits its bounded source call.
- **Deny:** Revoked, expired, restored, or uncertain connections produce no post-acknowledgement source dispatch or worker-visible byte, including buffered responses, established streams, and a crashed broker replica.

## Risk and disable path

- **Risk:** A refresh, replica crash, or restore may keep an old source grant active after disconnect acknowledgement or return buffered protected bytes.
- **Disable path:** Close the affected broker source dispatch and response gates, revoke upstream tokens where supported, and hold private jobs pending until the independent denial ledger, active-call registry, and recovery generation are verified.

## Dependency and closure gate

[CR-0004](CR-0004-oauth-mcp-adapter.md); independent denial ledger, active-call registry, source revocation capability, and recovery plan.

This repository is a design scaffold; this CR records work to be implemented and does not claim a running service or live conformance result. Close the CR only when its paired ToDo has the implementation pull request, versioned positive and negative evidence, and reconciled requirements, architecture, design, contracts, and component documentation. If this impact is withdrawn, record the reason and update both documents and the design links.
