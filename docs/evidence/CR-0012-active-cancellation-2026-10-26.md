# CR-0012 local synthetic active-cancellation attempt

- **Date:** 2026-10-26
- **Scope:** Disposable, credential-free fixture graph on an isolated loopback OpenShell v0.1.5 Docker gateway; no real OpenAI call or enterprise data
- **Worker image:** `localhost/openshell-research-spike@sha256:10df65b2418d529a9965ef87394218ab09c22d43e2fad9aee35e38c7e1f5c0ec` (local Linux ARM64 multi-platform index)
- **Base:** `python:3.13.17-slim-trixie@sha256:d98cc29d3266e535dd9da1099688d9cb3ca4753813571e071763d17725460962`
- **Gateway/CLI:** isolated v0.1.5 binary at `http://127.0.0.1:17671`; prior pinned binary/supervisor/runtime hashes remain in the [version manifest](../../spikes/full_graph/version-manifest.json). No production gateway image or Kubernetes CNI was used.
- **Sandbox:** `spike-cancel-2`, absent before creation and after deletion

## Observed sequence

The current source was rebuilt into the image above. A fresh localhost credential-free fixture model on port 8766 used `--delay-first-response-seconds 20` and an empty audit path. The launcher created the sandbox with its initial policy, inspected exact effective policy (`policy_hash=34ed977b0b553f714fcbcca0057329db12b708e68ca852025ec03df8a2bcb7a6`, loaded revision `2546471532142409492`) and zero attached providers, verified the baked worker/manifest hash, and observed direct IP plus disallowed REST method/path denials. It then launched the full graph, waited for the first audited `plan` model request while that response was held, requested sandbox deletion, waited for worker exec to stop and the sandbox to be absent, and waited beyond the model hold.

The launcher exited 0 with `active_plan_request_observed=true`, `active_cancellation_observed=true`, `worker_exec_stopped_after_delete=true`, `delete_accepted=true`, and `sandbox_absent_after_delete=true`. The final model audit contained **one total request**, the initial plan request, and no later retrieval request; the fixed graph needs a later retrieval model response before any `read_fixture` tool call. The current observation field `model_requests_after_cancel: 1` denotes the total audit count **at the post-cancellation checkpoint**, not a newly dispatched request after cancellation. The implementer has been asked to make that field unambiguous before final handoff.

| Local artifact | SHA-256 | Meaning |
|---|---|---|
| `/private/tmp/research-spike-cancel-2/observations/observations.json` | `5a90386c2d93cc80d0f83310131adefcddb9b6e03f4eee7fe544af72ab037a2b` | Sanitized structured allow/deny and cleanup observations |
| `/private/tmp/aurora-cancel-audit-2.jsonl` | `8a21e0c082c4c0a5fe09b14c3886531c5c08eef6c295db0f80e556d20b24922d` | One credential-free `plan` request with a 20-second held response |

## Limits and next gates

This proves local synthetic deletion during an active model request, observed worker stop, sandbox absence, and no subsequent fixture-model request under the fixed graph. It does not prove production model-gate upstream cancellation/stream draining, sender binding, Kubernetes ingress/egress CNI, a matched restricted worker, or real-model usage. The rebuilt image has not received a fresh final-digest CVE disposition; the prior exact-image local scan reported 48 high findings and already blocked promotion. [CR-0012](../change-requests/CR-0012-full-graph-runtime-spike.md), its [ToDo](../todos/CR-0012-full-graph-runtime-spike.md), and [CR-0013](../change-requests/CR-0013-build-security-pipeline.md) remain open pending their full gates and independent review of this attempt.
