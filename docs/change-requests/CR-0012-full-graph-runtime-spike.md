# CR-0012: Prove the complete research graph runs inside OpenShell

- **ID:** CR-0012
- **Status:** In progress
- **Impact ID:** DR-FEAS-002
- **Phase:** Milestones 0–1, before dashboard/control-plane implementation
- **Accountable team:** Research worker and runtime platform teams (proposed)
- **Component paths:** spikes/full_graph/ (planned), infra/openshell/, docs/progress-report.md
- **Requirement IDs:** SEL-04, RES-01, RES-09, NFR-01; IAM-05/RES-11/IAM-12 belong to [CR-0015](CR-0015-phase0-attempt-identity-readiness.md) and [CR-0016](CR-0016-phase1-sender-origin-proof.md) after selection
- **Primary design:** [Implementation plan](../design/implementation-plan.md)
- **Detailed design:** [Research worker](../design/research-and-evidence.md), [deployment and runtime gates](../design/deployment-and-operations.md#10-promotion-integration-gates)
- **Paired ToDo:** [Implementation and proof checklist](../todos/CR-0012-full-graph-runtime-spike.md)

## Impact on the application

This is an implementation intake for the existing full-graph runtime requirement; intended behavior is unchanged. At intake there was no runnable worker or sandbox harness. The LangChain OpenShell backend pattern alone did not show that the planner, retriever, synthesizer, and verifier process is inside OpenShell. The disposable harness now has a local synthetic full-graph observation; it remains distinct from an authenticated application Job API.

## Change request

Build a disposable public/synthetic Deep Agents worker image whose entrypoint starts the complete graph inside an OpenShell job sandbox. Keep a small host-side launcher for provisioning, bounded stage identity, policy inspection, cancellation, and cleanup. Use a fixed source/evidence fixture shared with a conventional restricted-worker comparator. A host-side model relay resolves only an approved credential reference or workload identity, pins the exact model, and caps spend; no reusable model or source secret enters the worker. Pin the compatible OpenShell gateway/CLI/SDK, supervisor/runtime, worker, Deep Agents/LangGraph, model client, prompt, and fixture versions before live claims.

## Required behavior

- **Accept:** Instrumentation from a real job sandbox proves all graph steps run inside it. The approved fixture/model path succeeds with bounded evidence and citations; effective OpenShell policy and provider receipts are inspected; direct worker egress, wrong-stage/manifest scope, and unapproved tools fail; active cancellation and observed sandbox deletion clean up the attempt. The restricted worker consumes the same fixtures and result shape for SEL-04 comparison.
- **Deny:** A host-side graph that only sends shell operations into OpenShell, an unverified policy/provider state, a wrong stage or fixture scope, a direct worker model/source call, or an unobserved cleanup cannot be reported as passing full-graph conformance. A matching copied stage header may pass this disposable harness; it is **not** sender authentication or copied-raw-bearer denial. Phase 0 Job API/model-gate attempt binding and Phase 1 sender proof have separate [CR-0015](CR-0015-phase0-attempt-identity-readiness.md) / [ToDo](../todos/CR-0015-phase0-attempt-identity-readiness.md) and [CR-0016](CR-0016-phase1-sender-origin-proof.md) / [ToDo](../todos/CR-0016-phase1-sender-origin-proof.md) implementation gates.

## Risk and disable path

Keep the harness disposable, synthetic/public only, and separate from the application release image. If the installed OpenShell APIs or node runtime cannot satisfy the required placement/policy proof, stop the live spike, retain sanitized failure evidence, and use the restricted-worker case as the comparison. Do not infer Kubernetes CNI enforcement from local Docker policy.

## Dependency and closure gate

Code and deterministic tests can be built before a live gateway is available. Keep this CR `In progress` until the exact version manifest, real sandbox process-location/policy/egress/active-cancel/cleanup evidence, restricted-worker matched result, and independent review are recorded in the paired ToDo. A fixture-only local process is not closure evidence. The [independent re-review](../evidence/CR-0012-0014-re-review-2026-10-26.md) confirms the local synthetic run while leaving those gates open.
