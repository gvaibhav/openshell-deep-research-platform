# CR-0012: independent principal engineer review

- **Date:** 2026-10-26
- **Reviewer:** `/root/milestone0_spike_review`, read-only sub-agent using the [principal engineer review skill](../../.agents/skills/principal-engineer-review/SKILL.md).
- **Scope:** `spikes/full_graph/`, its synthetic fixtures and tests, the first v0.1.5 runtime observations, and the [CR-0012](../change-requests/CR-0012-full-graph-runtime-spike.md) acceptance boundary.
- **Result:** One Blocker and five Important findings. CR-0012 remains `In progress`; no full-graph live success is established.

| Severity | Finding | Required correction or proof |
|---|---|---|
| Blocker | The initial filesystem policy omits read access to the baked `/opt/spike` worker path. The first live attempt could not import `spike.worker`. | Add the complete initial read-only path, start a fresh sandbox, inspect effective policy, and prove all four graph stages in-sandbox. [Attempt evidence](CR-0012-full-graph-attempt-1-2026-10-26.md). |
| Important | `ResearchWorker` counts Deep Agents invocations, while one invocation can issue several actual model requests through tools. | Enforce the manifest cap on actual relay requests; exercise a tool-call round trip and exhausted-budget denial. |
| Important | The launcher accepts substring matches in effective-policy text and does not prove exact route, admission state, revision, or provider absence. A direct-IP probe does not prove REST method/path enforcement. | Parse v0.1.5 structured sandbox/policy output; inspect exact effective route and provider state; live-probe allowed POST plus denied GET and wrong-path POST on the allowed host. |
| Important | Retrieval embeds selected evidence before model/tool use, and the stub never calls `read_fixture`; four verified stages can pass without a source-tool authorization decision. | Observe an admitted `read_fixture` call and deny an unadmitted ID, with the actual effective tool set inspected. |
| Important | Cleanup starts only after `create` returns success, leaving an uncertain-create orphan possible. Failed CLI errors omit the operation name. | Reconcile and delete by sandbox name after a timeout or uncertain create; retain a sanitized operation label and observed absence. |
| Important | The restricted comparator targets one relay Pod IP in the URL but permits every Pod with a generic relay label. | Bind the policy selector to the intended attempt and prove the actual allowed/denied target under a live enforcing CNI. |

The reviewer ran 19 deterministic unit tests, Ruff, mypy, and `make check` successfully. Those tests inject a fake graph and agent. Full-graph execution, tool inspection, cancellation, copied identity denial, authenticated real-model relay ingress, restricted-worker CNI/matched comparison, and final-image CVE disposition remain unrun. The credential-bearing relay correctly remains loopback-only; its stage header is copyable and is not a production sender binding.

**Disposition:** Root assigned a TDD correction slice back to `/root/milestone0_spike`. Re-review the changed code and live evidence before treating any CR-0012 gate as passed.
