# CR-0015: Bind the Phase 0 worker attempt at the Job API and model gate

- **ID:** CR-0015
- **Status:** Open
- **Impact ID:** DR-ID-001
- **Phase:** Milestones 2–3, only after the SEL-01/02/04/05 selection decision; public/synthetic Phase 0
- **Accountable team:** Application identity, controller, and model-platform teams (proposed)
- **Component paths:** Planned `services/job-api/`, `services/controller/`, `services/provider-provisioner/`, `services/model-gate/`, `worker/ingress/`, and `contracts/internal/attempt-readiness.schema.json`; exact paths and contract fields confirmed before code; `docs/design/identity-and-access.md`, `docs/design/job-lifecycle.md`, `docs/design/research-and-evidence.md`
- **Requirement IDs:** IAM-05, IAM-13, RES-11, JOB-02
- **Primary design:** [Phase-specific identity handoff](../design/identity-and-access.md#phase-specific-implementation-intake)
- **Impact analysis:** [Proof-boundary reconciliation](../design/implementation-plan.md#8-proof-boundary-reconciliation-and-identity-intake)
- **Paired ToDo:** [Implementation and proof checklist](../todos/CR-0015-phase0-attempt-identity-readiness.md)

## Current and target behavior

The disposable [CR-0012](CR-0012-full-graph-runtime-spike.md) harness checks a copyable stage string against a fixed manifest. It has no application Job API, durable attempt record, per-attempt OpenShell provider receipt, or trusted model-gate readiness record. Its stage check is not worker authentication. This CR is an implementation intake for the **existing** Phase 0 identity/readiness design; it does not change that design or authorize the post-selection build before the platform-selection gate.

Build a server-held, expiring job/stage/sandbox/attempt/recovery-generation identity for each public worker, delivered through a distinct per-attempt OpenShell Job API provider only after the inert-sentinel, immutable-sandbox, exact-provider/effective-policy, and attempt-ready sequence passes. The Job API and separately audienced model gate consult the authoritative current binding before each admitted call. Define and version the internal worker-attempt/readiness contract before dependent component code; the path and fields belong in the paired ToDo. A raw stolen static bearer remains a documented Phase 0 replay limit; [CR-0016](CR-0016-phase1-sender-origin-proof.md) owns sender proof before private data.

## Required behavior

- **Accept:** A current worker can fetch only its stage manifest and submit bounded stage events, checkpoints, evidence references, and report candidates; a ready model request reaches only its approved route under the separate gate audience. Trusted capture, not the worker, creates canonical source evidence. The server records the immutable sandbox ID, attempt, policy/provider receipts, current fence and external recovery generation before releasing the manifest or a model call.
- **Deny:** Wrong job, stage, sandbox binding, attempt, audience, expired or revoked identity, stale fence/recovery generation, copied placeholder without the right provider attachment, pre-ready/uncertain-create model call, and a controller request using provisioner authority. A copied raw static bearer from a different origin is **not** represented as denied in Phase 0; it is the explicit public-prototype residual risk.

## Dependencies, risk, and disable path

Depends on a positive SEL selection decision, an approved service/contract owner, the exact OpenShell provider/profile behavior on the chosen runtime, and separate provisioner/controller credentials. Incorrect activation could release a manifest or vendor model call to the wrong attempt. Keep the Job API and model gate closed until exact receipt/readiness proof is committed; revoke the attempt and delete the sandbox on mismatch, timeout, or rollback. No private data is admitted under the static bearer fallback.

## Closure gate

The paired ToDo must link the versioned internal contract, component PRs, pinned runtime/profile versions, allow and deny tests, and live nonproduction provider/ready/uncertain-create observations. Independent identity/runtime review must find the as-built design consistent. This CR does not claim the complete RES-11 request-schema, class, usage, and cost gate; a separate implementation intake is required before that component is built.
