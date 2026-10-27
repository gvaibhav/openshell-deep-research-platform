# ToDo for CR-0015: Phase 0 worker attempt identity and readiness

- **ID:** CR-0015
- **Status:** Open
- **Impact ID:** DR-ID-001
- **Phase:** Milestones 2–3 after a positive SEL decision; public/synthetic only
- **Accountable team:** Application identity, controller, and model-platform teams (proposed)
- **Component paths:** Planned `services/job-api/`, `services/controller/`, `services/provider-provisioner/`, `services/model-gate/`, `worker/ingress/`, and `contracts/internal/attempt-readiness.schema.json`; confirm exact paths before code
- **Requirement IDs:** IAM-05, IAM-13, RES-11, JOB-02
- **Change request:** [CR-0015](../change-requests/CR-0015-phase0-attempt-identity-readiness.md)
- **Design baseline:** [Phase-specific identity handoff](../design/identity-and-access.md#phase-specific-implementation-intake)

## Implementation and proof checklist

- [ ] After the SEL gate, designate owners and specify a versioned internal worker-attempt/readiness contract under `contracts/internal/` **before** Job API, controller, provisioner, or model-gate code consumes it. Include exact issuer/audience, job/stage/sandbox/attempt/recovery generation, expiry/revocation, provider receipt, readiness, bounded operations, and error semantics; add valid and denied fixtures.
- [ ] Write failing TDD cases for a valid current attempt and wrong job, stage, sandbox, attempt, audience, expiry, revocation, fence, recovery generation, missing/wrong provider receipt, pre-ready and uncertain-create calls, and wrong controller/provisioner authority.
- [ ] Implement separate restricted controller and provisioner identities, inert initial Job API/model-gate providers, immutable sandbox binding, receipt reconciliation, and one authoritative attempt-ready transition. Keep bootstrap, retry, cancellation, and restore paths closed until a fresh committed ready record exists.
- [ ] Implement Job API and model-gate receiver checks on every call, with bounded manifest/events/checkpoints/evidence-reference/report-candidate operations and canonical evidence accepted only from trusted capture. Keep the two service audiences distinct.
- [ ] Run live nonproduction OpenShell tests on pinned gateway/supervisor/runtime/CLI/profile versions for placeholder resolution only at the approved endpoint, wrong-sandbox copied-placeholder denial, uncertain-create cleanup, pre-ready model denial, and observed cancellation/revocation. Record the static raw-bearer replay limit without calling it sender proof.
- [ ] Update architecture, identity, lifecycle, research design, contracts, examples, and release gates for any implementation difference; obtain independent identity/runtime review and record the exact PRs, allow/deny evidence, and disable path.

## Completion evidence

- **Selection decision and component PRs:** Pending.
- **Internal contract and fixtures:** Planned `contracts/internal/attempt-readiness.schema.json` and `examples/attempt-readiness-{allow,deny}.json`; not yet specified or implemented. This is a pre-implementation gate.
- **TDD and live allow/deny evidence:** Pending.
- **Independent review and closure:** Pending. Keep `Open` until the application components and proof exist; the synthetic spike cannot close this pair.
