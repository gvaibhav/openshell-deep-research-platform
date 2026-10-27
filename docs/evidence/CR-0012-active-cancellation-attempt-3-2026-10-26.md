# CR-0012: current-image synthetic active cancellation

- **Date and data:** 2026-10-26; invented Aurora fixture and credential-free local model stub. No OpenAI key, upstream model call, or enterprise source.
- **Runtime:** Isolated local OpenShell CLI/gateway v0.1.5 with Docker driver at `127.0.0.1:17671`; disposable sandbox `spike-cancel-3`.
- **Worker image:** `localhost/openshell-research-spike@sha256:bbf9907a5422c836fb10cd1c3b83959f2aef997a5fad2e7f70bab68aeab3909a` on Linux ARM64. This is the same immutable image as the [current completed graph](CR-0012-full-graph-attempt-6-2026-10-26.md). The prior [cancellation attempt](CR-0012-active-cancellation-2026-10-26.md) used `sha256:10df65b2…`.
- **Disposition:** Launcher exited 0. [CR-0012](../change-requests/CR-0012-full-graph-runtime-spike.md) and its [ToDo](../todos/CR-0012-full-graph-runtime-spike.md) remain `In progress` for the matched restricted-worker/CNI, approved real-model, and release gates.

## Ordered observations

The fresh host stub listened on port 8769, wrote only sanitized request counts and tool names to an initially absent audit file, and held its first `plan` response for 20 seconds. The launcher created the sandbox, inspected exact effective policy hash `cac212061fd4018cb72115e4ffd7dd9ccb46c5379fbd6f23847a6813a800655e` and loaded revision `12812715874154074032`, and observed **zero attached providers**. The authored policy SHA-256 was `21138dde048544df65ec6e21bcfc2ee2f57600c89e6ba606daa97acfad9d2437`.

Before the admitted worker run, the launcher verified the baked import/read-only code and stage file SHA-256 `cb5dda185437cdbe52617e777fc05ee3ad3e334f373ef6649d0bca75719f5555`. It observed wrong-stage denial with the model audit unchanged, unadmitted fixture-ID denial, direct network denial, and OpenShell relay GET/wrong-path POST policy denial. These checks do not prove receiver-verified application sender identity.

The launcher then observed the first audited `plan` model request while the response was held, requested sandbox deletion, observed the worker CLI exec stop and sandbox absence, and waited beyond the hold. The final audit contained **one total request** and zero new requests after deletion; no retrieval model request occurred, so the fixed graph could not reach `read_fixture`. A separate `sandbox list --output json` returned `sandboxes: []`. The stub was stopped after the observations.

| Local artifact | SHA-256 |
|---|---|
| `/private/tmp/research-spike-cancel-3/observations/observations.json` | `82be59ce8fd4c76d4aa1623466abc7345a0f590d9ebef4dd65a6d03f29c3693e` |
| `/private/tmp/aurora-cancel-audit-3-20261026.jsonl` | `8a21e0c082c4c0a5fe09b14c3886531c5c08eef6c295db0f80e556d20b24922d` |
| `/private/tmp/research-spike-cancel-3/policy.yaml` | `21138dde048544df65ec6e21bcfc2ee2f57600c89e6ba606daa97acfad9d2437` |

These disposable local files are observations, not retained release artifacts. The [version manifest](../../spikes/full_graph/version-manifest.json) pins the image, runtime, source, fixture, and prior attempts.

## Limits

This proves local synthetic deletion during an active model request, worker stop, sandbox absence, and no later fixture-model request on the same image used for the completed graph. It does not prove production upstream stream draining, authenticated relay ingress, Kubernetes CNI isolation, or a real-model cancellation path. The [exact-image scan](CR-0013-local-image-scan-2026-10-26.md#latest-wrong-stage-and-full-graph-image-preflight) has 48 high findings and blocks promotion under the proposed policy.
