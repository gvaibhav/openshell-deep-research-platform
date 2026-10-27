# CR-0012: corrected development image, full synthetic graph and active cancellation

**Date and scope:** 2026-10-26, invented Aurora fixture and credential-free host model stub. This is a local Docker-driver OpenShell test of [CR-0012](../change-requests/CR-0012-full-graph-runtime-spike.md) / [ToDo](../todos/CR-0012-full-graph-runtime-spike.md) on the caller-pinned [CR-0013 corrected development image](CR-0013-pip-ensurepip-removal-candidate-2026-10-26.md) / [ToDo](../todos/CR-0013-build-security-pipeline.md). No real model key, upstream call, employee data, or enterprise source was used. Independent runtime review matched the raw hashes, policy/provider, graph, citation, model audit, and cancellation observations and found no local code Blocker/Important after documentation reconciliation.

| Pinned input | Value |
|---|---|
| Worker | `localhost/openshell-research-spike@sha256:8548ebaf60475d442eb8dae16b1b414a66283f68ec369af2ed4f2e7f49be1292`, `linux/arm64`; 60-package worker lock SHA-256 `37f289695d47e21daf3096c0de4f71fcd111d9378ed4e10f75fd61db735331b7`. |
| OpenShell | Isolated macOS ARM64 gateway and CLI v0.1.5, CLI SHA-256 `96cbf2910fd670f9f49eb1cf7663c8dce5398ffa2617ee1c6ba8f5d9c9fa8302`, gateway binary SHA-256 `60b562d2d78cab122bd998f14f6b5a22f1a20e4bb77943a25498caee8d041ec9`, supervisor `sha256:fabcd01f656e9d23df4386f82e80b4f48b90f3452d7d5c58889007643a069161`, sandbox runtime `sha256:e9adf9ecde328122414ad2ee8c6fc5d5b389e4cf168daf4357c46f5a77d55851`. Disposable gateway bound only to `127.0.0.1:17671` with loopback health port 17672, local unauthenticated access, no enterprise traffic; it was stopped after the tests. |
| Frozen source | Worker, model stub, relay, launcher, and lock SHA-256 values match the [version manifest](../../spikes/full_graph/version-manifest.json). The Dockerfile correction removes build-only pip/ensurepip from the image's effective runtime filesystem; this record does not claim a byte-for-byte diff of every image layer. |

## Full-graph attempt

Sandbox `spike-8548eb-1` used a fresh credential-free stub at `host.docker.internal:8770`; the gateway health check reported v0.1.5 and a healthy database. The launcher exited 0. The uploaded stage file SHA-256 was `cb5dda185437cdbe52617e777fc05ee3ad3e334f373ef6649d0bca75719f5555`. An intentionally wrong expected stage exited before model contact and left the fresh model audit unchanged. The same sandbox then completed `plan → retrieve → synthesize → verify`, all with PID 99, hostname `610a0d70bbb0`, and PID namespace `pid:[4026532708]`. The worker verified two cited claims against two admitted source records (`ownership`, `runbook`), with six actual fixture-model HTTP requests.

The launcher inspected loaded sandbox policy revision `812576178294061669`, effective policy hash `d0eb212005020df6fb6cad32153c8c6ce6e3b70e74fa668aa285b068b2a6b907`, zero attached providers, and read-only baked worker code. Direct egress, relay GET, relay wrong-path POST, and an unadmitted fixture ID were denied. Sandbox deletion was accepted and absence observed. The authored policy SHA-256 was `cc2ec088f407f66fab838eead9bf9b7ba667b3e333d49db57000036c1fc1160c`.

| Disposable full-graph artifact | SHA-256 |
|---|---|
| `/private/tmp/research-spike-aurora-8548eb-2/observations/observations.json` | `8c02101d2c10ce8a70d2807d7a39733c70e11881cf1048a8e10a0eac60434574` |
| `/private/tmp/research-spike-aurora-8548eb-2/observations/result.json` | `65dba20dd744054b362ee47fad064ec604532862d6539042bc8f9f49167d5c19` |
| `/private/tmp/aurora-model-audit-8548eb-1.jsonl` | `0ce9c33ab40ef52b55de1a6b48228c65ff0705c6dcc14385ccd0c45bc1c861a9` |

## Active cancellation attempt

Fresh sandbox `cancel-8548eb-1` used a separate stub at `host.docker.internal:8771` that held its first plan response for 20 seconds. Before the admitted call, the launcher again verified baked code, the same stage-file digest, wrong-stage/no-model denial, unadmitted fixture denial, direct egress denial, GET/wrong-path POST denial, effective policy hash `6a514a3968373b9e33995e704c501c003302f42358324ebd78215cb5e29acc3c`, and zero attached providers. Its authored policy SHA-256 was `4f9cfd7c5d0e34dca0f2ea250147e61e7fc076adc82c29cbca4037e79876fb3e`.

The host audit recorded the first plan request while its response was held. Deletion was accepted, the worker CLI exec stopped, and the sandbox was absent. After waiting past the hold, the audit still had **one total model request**, **zero new model requests**, and **zero later retrieval requests**. A separate `sandbox list --output json` returned an empty array after both attempts. Both fixture stubs and the loopback gateway were stopped.

| Disposable cancellation artifact | SHA-256 |
|---|---|
| `/private/tmp/research-spike-cancel-8548eb-1/observations/observations.json` | `55cb5e3d8982f17abecab0a20973e0fe56aa8a6cee97eb6d394918724c87d662` |
| `/private/tmp/aurora-cancel-audit-8548eb-1.jsonl` | `8a21e0c082c4c0a5fe09b14c3886531c5c08eef6c295db0f80e556d20b24922d` |

## Limits

These local observations requested the same immutable corrected image digest for the graph and cancellation, but the retained `sandbox-get` artifact does not report a resolved worker image ID and the launcher did not retain the create response as an image-resolution receipt. The digest is pinned by the caller's command and locally inspected image, not independently attested by the gateway; a release gate needs a stronger resolved-image receipt. A separate [network-disabled strict model-body run](CR-0014-corrected-image-network-disabled-body-2026-10-26.md) also passed on the corrected image. This image still has **44 HIGH Debian findings**, one UNKNOWN and undispositioned lower findings. The scan and SBOM do not establish byte-level absence from inherited OCI layers. No Kubernetes CNI, restricted-worker matched comparison, real model, authenticated Job API/model relay ingress, provider attachment, enterprise authorization, or release approval was tested here. A stage header remains copyable. [CR-0015](../change-requests/CR-0015-phase0-attempt-identity-readiness.md) / [ToDo](../todos/CR-0015-phase0-attempt-identity-readiness.md) and [CR-0016](../change-requests/CR-0016-phase1-sender-origin-proof.md) / [ToDo](../todos/CR-0016-phase1-sender-origin-proof.md) own application sender proof. The local gateway permitted unauthenticated loopback clients solely for synthetic testing.
