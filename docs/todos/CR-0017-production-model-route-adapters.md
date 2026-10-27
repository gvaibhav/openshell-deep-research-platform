# ToDo for CR-0017: Production model route and provider adapters

- **ID:** CR-0017
- **Status:** Open
- **Impact ID:** DR-MODEL-002
- **Phase:** Milestones 2–3 after a positive SEL decision; before live public model traffic
- **Accountable team:** Model-platform and application teams (proposed)
- **Component paths:** Planned `services/model-gate/`, `services/model-gate/providers/`, `config/model-routes/`, and `contracts/internal/model-route.schema.json`; confirm exact paths before code
- **Requirement IDs:** RES-11, NFR-07, IAM-05, OPS-10
- **Change request:** [CR-0017](../change-requests/CR-0017-production-model-route-adapters.md)
- **Design baseline:** [Production provider route impact](../design/research-and-evidence.md#production-provider-adapter-and-route-catalog-impact)

## Implementation and proof checklist

- [ ] After a positive SEL decision, name model/security owners and record the approved provider, exact endpoint/model, maximum data class, data-processing/trace/retention terms, prompt version, pricing revision, credential reference, per-stage limits, and disable owner.
- [ ] Define a versioned internal route-catalog and provider-adapter contract under `contracts/internal/` **before** dependent model-gate code. Include route revision, provider/endpoint/model, native allowed body fields, class, trace, price, input/output bounds, response/usage mapping, cancellation semantics, and valid/denied examples. Keep the browser/job-policy `model_route` value an opaque alias.
- [ ] Write failing TDD cases for a ready exact route and unknown provider, wrong model on the same host, unreviewed nested tool/file/URL/multimodal fields, worker-supplied upstream auth, over-class context, pre-ready/stale attempt, concurrent and streaming budget exhaustion, ambiguous usage, active cancellation, and silent provider fallback.
- [ ] Implement the gate-owned adapter registry and reviewed route catalog; canonicalize upstream requests and bounded responses. Keep upstream credentials and traces at the trusted gate; use [CR-0015](../change-requests/CR-0015-phase0-attempt-identity-readiness.md) readiness and the Phase 1 [CR-0016](../change-requests/CR-0016-phase1-sender-origin-proof.md) sender gate when private data is enabled.
- [ ] Record atomic worst-case request/input/output/estimated-cost reservations in an independently recoverable ledger. Close active upstream calls and worker-visible streams on cancel, retry, expiry, or recovery fence; retain conservative charges for uncertain usage.
- [ ] Qualify the first adapter with fake upstream allow/deny tests, then approved nonproduction real-model calls on pinned versions and class. Test a second fake provider/route switch with a fresh snapshot/attempt and denial of in-flight route mutation; no second vendor key is required for this test.
- [ ] Reconcile architecture, identity/research/lifecycle designs, contracts, configuration, release manifest, evaluations, and runbook with the as-built gate; run dependency/final-digest CVE scans and independent model/security review before marking verified.

## Completion evidence

- **Selection decision, component PRs, and approved route:** Pending.
- **Internal route contract and examples:** Planned `contracts/internal/model-route.schema.json` and `examples/model-route-{allow,deny}.json`; not yet specified or implemented. This is a pre-implementation gate.
- **TDD, fake/real upstream, usage/cancellation, and scan evidence:** Pending.
- **Independent review and closure:** Pending. The local CR-0014 adapter is not production model-gate proof.
