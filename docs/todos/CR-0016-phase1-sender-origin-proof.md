# ToDo for CR-0016: Phase 1 sender origin proof

- **ID:** CR-0016
- **Status:** Open
- **Impact ID:** DR-ID-002
- **Phase:** Phase 1 before live enterprise source data
- **Accountable team:** Platform identity, Job API, connector broker, and model-platform teams (proposed)
- **Component paths:** Planned `infra/identity/sandbox-ingress/`, `services/job-api/`, `services/connector-broker/`, `services/model-gate/`, and `contracts/internal/sender-origin.schema.json`; select exact mechanism and paths before code
- **Requirement IDs:** IAM-05, IAM-12, RES-11
- **Change request:** [CR-0016](../change-requests/CR-0016-phase1-sender-origin-proof.md)
- **Design baseline:** [Phase-specific identity handoff](../design/identity-and-access.md#phase-specific-implementation-intake)

## Implementation and proof checklist

- [ ] After deployment target selection, choose a receiver-verified sandbox/attempt identity, document trust root, issuance, rotation, revocation, and exact ingress route. Record a threat model for spoofed headers, cross-Pod token replay, stale sandboxes, and ingress bypass.
- [ ] Specify a versioned internal sender-origin contract under `contracts/internal/` before receiver/ingress code, with valid and denied fixtures and exact failure semantics. Do not accept a worker-supplied identity assertion as trusted origin.
- [ ] Write failing TDD cases for current sender allow; copied raw bearer from a different client and sandbox deny; forged/missing origin deny; another job/stage/attempt deny; old proof, stale recovery generation, and revoked proof deny at Job API, broker, and model gate.
- [ ] Implement the selected trusted ingress and receiver checks, and enforce the qualified Kubernetes network path so workers cannot bypass it or reach a receiver directly with only a bearer. Keep source and private model routes closed until current origin and attempt binding both pass.
- [ ] Run live pinned OpenShell/cluster/CNI tests across separate sandboxes and tenants, including replay after retry, rotation, cancellation, rollback, and restore. Record no source/model dispatch and no protected response bytes for denied requests.
- [ ] Reconcile architecture, Okta handoff if an Okta-managed issuer is actually selected, identity/lifecycle/research designs, contracts, examples, and runbooks; obtain independent identity/platform/source review and record PRs, allow/deny evidence, and disable path.

## Completion evidence

- **Chosen origin mechanism, owner, runtime, and component PRs:** Pending.
- **Internal contract and fixtures:** Planned `contracts/internal/sender-origin.schema.json` and `examples/sender-origin-{allow,deny}.json`; not yet specified because the deployed trust mechanism is unselected. This is a pre-implementation gate.
- **TDD and live cross-origin allow/deny evidence:** Pending.
- **Independent review and closure:** Pending. Keep `Open` and private worker traffic disabled until all receiver boundaries pass.
