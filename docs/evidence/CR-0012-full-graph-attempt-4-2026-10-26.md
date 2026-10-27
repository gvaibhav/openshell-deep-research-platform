# CR-0012: successful synthetic full-graph launcher attempt

- **Date:** 2026-10-26
- **Data:** Fixed synthetic Aurora fixture; credential-free host model stub. No real provider key or enterprise source.
- **Runtime:** Isolated local OpenShell CLI/gateway v0.1.5 with Docker driver; sandbox `spike-aurora-4`.
- **Image:** `localhost/openshell-research-spike@sha256:101057cb501f64b4e16c2df3185af4dcccdae15fc906961cd3abc6680e43c5ec`, built on pinned Python 3.13.17 slim Trixie. This remains a development artifact with unresolved high OS findings under the proposed CVE gate.
- **Status:** The corrected synthetic launcher exited 0. This is local runtime evidence; [CR-0012](../change-requests/CR-0012-full-graph-runtime-spike.md) remains `In progress` pending independent review and other named gates.

## Observed allow and deny behavior

| Boundary | Observation |
|---|---|
| Sandbox and effective policy | `Ready`; accepted config revision `6195511749704502767`, canonical effective policy hash `6bb7a0fb07ef644f58b9d8243bfd875b458c74c3bf6f64d218f1c30c7d3b37da`, exact one `model_relay` POST `/v1/chat/completions` route, required read-only code paths and hard Landlock compatibility. `sandbox provider list -o json` had zero providers. |
| Worker and stage | Baked package import and read-only access passed. Unfiltered upload produced a regular manifest file whose in-sandbox SHA-256 matched `cb5dda185437cdbe52617e777fc05ee3ad3e334f373ef6649d0bca75719f5555`. The result reported all four steps `plan → retrieve → synthesize → verify`, `verified=true`, two retained evidence items, and two cited claims. All four step markers had PID 98, hostname `7e1ce5124a2f`, and PID namespace `pid:[4026532708]`. The prior [manual run](CR-0012-manual-full-graph-2026-10-26.md) matched its analogous hostname directly to its Docker worker container; the integrated attempt did not separately capture its container ID before deletion. |
| Fixture tools and model requests | The result recorded two **allowed** `read_fixture` calls for `ownership` and `runbook` and **six actual HTTP model requests** against the stage cap of eight. A separate in-worker call with the same admitted evidence set denied an existing unadmitted fixture source. The host-only sanitized model audit showed tool catalogs `[]` for plan/synthesis/verify and `['read_fixture']` for the three retrieval requests (two tool calls and a final answer). |
| Network | Direct TCP to `1.1.1.1:443` failed with policy denial. GET `/v1/chat/completions` and POST `/v1/wrong-path` to the otherwise allowed relay host each returned OpenShell HTTP 403 `policy_denied` at L7. The six valid model POSTs reached only the credential-free stub. |
| Cleanup | Sandbox deletion was accepted, the launcher observed it absent, and a subsequent `sandbox list -o json` returned an empty sandbox array. |

The local observations and result remain under `/private/tmp/cr0012-live-20261026-4/observations/`; the sanitized stub audit remains `/private/tmp/cr0012-stub-audit-4.jsonl`. Those temporary files are not a durable release record. No model/source credential appeared in worker inputs or this evidence.

## Remaining gates

An independent reviewer must inspect the corrected code and saved policy/provider/result observations before upgrading the process-location/policy claim. Cancellation during a live graph, copied-identity denial, authenticated real-model ingress and use of the user's selected `gpt-5.6-sol`, a matched restricted-worker run under an enforcing CNI, final exact-image/platform CVE/SBOM disposition, and ChatGPT Enterprise comparison remain unrun. The local Docker result does not prove Kubernetes isolation or production model-gate/Job API/broker controls. See the [paired ToDo](../todos/CR-0012-full-graph-runtime-spike.md) and [build security pair](../change-requests/CR-0013-build-security-pipeline.md).

**Re-review addendum, 2026-10-26:** The independent [re-review](CR-0012-0014-re-review-2026-10-26.md) corroborated this local synthetic observation. Its reference above to copied-identity denial is superseded as a CR-0012 closure test: a copied matching stage header is not sender proof. The current [CR-0012](../change-requests/CR-0012-full-graph-runtime-spike.md) requires wrong-stage/manifest and fixture-scope denial plus active cancellation; [CR-0015](../change-requests/CR-0015-phase0-attempt-identity-readiness.md) and [CR-0016](../change-requests/CR-0016-phase1-sender-origin-proof.md) own post-selection Phase 0 attempt binding and Phase 1 raw-bearer origin denial.
