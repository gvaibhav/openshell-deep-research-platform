# ToDo for CR-0014: Local model provider router

- **ID:** CR-0014
- **Status:** In progress
- **Impact ID:** DR-MODEL-001
- **Phase:** Milestones 0–1 synthetic spike
- **Accountable team:** Research worker and model-platform teams (proposed)
- **Component paths:** `spikes/full_graph/spike/relay.py`, provider helper and tests under `spikes/full_graph/`, `spikes/full_graph/relay-route.example.json`, `.env.example`, spike guide
- **Requirement IDs:** SEL-04, RES-01, RES-11, NFR-01
- **Change request:** [CR-0014](../change-requests/CR-0014-local-model-provider-router.md)
- **Design baseline:** [Local model route impact analysis](../design/implementation-plan.md#7-local-model-route-impact-analysis)

## Implementation and proof checklist

- [ ] Write failing tests for an unsupported provider, wrong endpoint/model, missing local host key, over-budget body, nested message/tool extras, image/URL/file parts, malformed `tool_calls`, worker placeholder-header replacement, and no key in the **launcher CLI child environment**, logs, manifests, image, or synthetic result.
- [ ] Implement an explicit registered provider adapter seam and OpenAI `gpt-5.6-sol` host relay route. Limit `RESEARCH_OPENAI_API_KEY` use to the local synthetic relay process; preserve file/reference and workload-identity modes where approved.
- [ ] Validate a text-only, role-specific message/tool schema and construct the upstream body solely from approved fields; a nested multimodal or malformed tool-call value must fail before upstream contact with a bounded error.
- [ ] Pass an explicit nonsecret environment allowlist to every launcher-spawned OpenShell CLI process and test an exported synthetic key is absent from those children. Document a process-scoped host-relay environment assignment or safe secret file reference.
- [ ] Update the nonsecret route example and spike guide. Pin exact model ID, route, body format, data class, prompt/client versions, reviewed maximum spend, and the official pricing revision before real traffic.
- [ ] Test a fake upstream locally with allowed and denied requests, then obtain an approved real nonproduction API call with sanitized usage/route evidence and no credential exposure. Do not send enterprise content during this spike.
- [ ] Reconcile [CR-0012](../change-requests/CR-0012-full-graph-runtime-spike.md) and the intended production model-gate design against the observed route; request an independent review of the adapter and custody boundary.

## Completion evidence

- **Implementation PR and versions:** Pending.
- **Red/green TDD:** Initial adapter tests were red before implementation, then the independent [re-review](../evidence/CR-0012-0014-re-review-2026-10-26.md) found inherited-key launcher and nested-body forwarding Blockers. Correction tests were red for class/mode, recursive text/tool validation, child-environment custody, active cancellation, ordered wrong-stage denial, and exact L7 policy-denial markers; 14 relay tests, 52 spike tests, the then-current full suite, Ruff, mypy, and `make check` passed after the fixes. See the [TDD record](../../spikes/full_graph/TDD-EVIDENCE.md).
- **Fake and real upstream evidence:** A recording fake upstream received only canonical text-only fields and a synthetic host canary in Authorization. A [new network-disabled corrected-image conformance run](../evidence/CR-0014-corrected-image-network-disabled-body-2026-10-26.md) on caller-pinned worker `sha256:8548ebaf…` exercised six real Deep Agents/LangChain request bodies through the validator, with 58,852 microUSD conservative synthetic reservation under the nonsecret 60,000 cap. Its sanitized output hash matches the prior `sha256:bbf9907a…` run, but this is a fresh exact-image observation. No real API key has been provided and no real upstream call occurred; authenticated sandbox ingress and approved real-model usage remain pending.
- **Independent review and owner route approval:** The first [read-only re-review](../evidence/CR-0012-0014-re-review-2026-10-26.md) identified the two real-key Blockers and missing class/mode enforcement. The [second re-review](../evidence/CR-0012-0014-second-re-review-2026-10-26.md) confirmed their synthetic-lane corrections and requested live wrong-stage proof and strict L7 marker checking. Both were implemented and observed in [attempt 6](../evidence/CR-0012-full-graph-attempt-6-2026-10-26.md); the [final read-only review](../evidence/CR-0012-0014-final-synthetic-review-2026-10-26.md) found no remaining Blocker or Important code issue in the synthetic slice and confirmed the evidence links. Route/price/ingress owner approval remains pending; do not use a real key yet.
- **Disable path:** Keep the credential-free fixture stub; unset the host environment variable and do not launch the real relay.
- **Closure:** Keep `In progress` until a reviewed route and local approved real-model observation pass. This pair does not verify the production model gate.
