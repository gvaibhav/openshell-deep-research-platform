# CR-0016: Prove sender origin before private worker traffic

- **ID:** CR-0016
- **Status:** Open
- **Impact ID:** DR-ID-002
- **Phase:** Phase 1, before live enterprise source data
- **Accountable team:** Platform identity, Job API, connector broker, and model-platform teams (proposed)
- **Component paths:** Planned `infra/identity/sandbox-ingress/`, `services/job-api/`, `services/connector-broker/`, `services/model-gate/`, and `contracts/internal/sender-origin.schema.json`; select the exact trust mechanism and paths before code; `docs/design/identity-and-access.md`, `docs/design/job-lifecycle.md`, `docs/design/research-and-evidence.md`
- **Requirement IDs:** IAM-05, IAM-12, RES-11
- **Primary design:** [Phase-specific identity handoff](../design/identity-and-access.md#phase-specific-implementation-intake)
- **Impact analysis:** [Proof-boundary reconciliation](../design/implementation-plan.md#8-proof-boundary-reconciliation-and-identity-intake)
- **Paired ToDo:** [Implementation and proof checklist](../todos/CR-0016-phase1-sender-origin-proof.md)

## Current and target behavior

The public Phase 0 design permits an endpoint-bound static OpenShell provider bearer, with an explicit raw-token replay limit. No sender-constrained enterprise receiver exists. This CR is an implementation intake for the already documented Phase 1 boundary, not a change to the intended identity flow. A copied raw bearer must be useless to a different client or sandbox before any private source data is admitted.

Choose and qualify a receiver-verified sandbox/attempt origin, such as SPIFFE/mTLS at a trusted ingress with exact identity binding, for worker calls to the Job API, connector broker, and private model gate. The receiver checks that origin **in addition to** the current job/stage/sandbox/attempt and external recovery-generation binding. A gateway-minted or OpenShell dynamic-grant bearer alone is not sender proof. Specify the versioned ingress-to-receiver contract and trust root after the deployment runtime is chosen, before dependent code.

## Required behavior

- **Accept:** The current sandbox sender with the current bound attempt can call only its approved Job API, broker, and model-gate operations through the qualified ingress; a rotated sender credential becomes active only for that same current attempt.
- **Deny:** A copied valid raw bearer from another sandbox, Pod, or client; a missing or forged origin header; an old sandbox after retry/restore; a sender proof for another job/stage/attempt; and a request after proof rotation or revocation. Denial occurs before manifest/content delivery, source dispatch, or upstream model dispatch.

## Dependencies, risk, and disable path

Depends on a selected OpenShift/GKE runtime, its enforced ingress/egress CNI path, platform trust root, receiver owner, and [CR-0015](CR-0015-phase0-attempt-identity-readiness.md). Until the live origin-denial matrix passes, the private connector and private model routes stay disabled; revoke worker credentials and quarantine old sandboxes on mismatch or rollback. No Okta browser PKCE token or dashboard session is substituted for a sandbox identity.

## Closure gate

The paired ToDo must link an implemented ingress/receiver contract, pinned trust/runtime versions, live cross-origin copied-bearer allow/deny evidence at all three receivers, rotation/restore tests, and independent platform/identity review. The Phase 0 synthetic stage check and endpoint-bound placeholder cannot close this pair.
