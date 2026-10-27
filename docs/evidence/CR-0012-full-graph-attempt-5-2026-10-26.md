# CR-0012: prior corrected-image synthetic full-graph attempt

- **Date:** 2026-10-26
- **Data and model:** Fixed synthetic Aurora fixture and a credential-free local model stub. No OpenAI key, real model call, or enterprise source was used.
- **Runtime:** Isolated local OpenShell CLI/gateway v0.1.5 with Docker driver at `127.0.0.1:17671`; sandbox `spike-aurora-5`.
- **Worker image:** `localhost/openshell-research-spike@sha256:10df65b2418d529a9965ef87394218ab09c22d43e2fad9aee35e38c7e1f5c0ec` on Linux ARM64, from the pinned Python 3.13.17 slim Trixie base and hash-locked worker packages. This local image is development-only.
- **Disposition:** Launcher exited 0. [CR-0012](../change-requests/CR-0012-full-graph-runtime-spike.md) and its [ToDo](../todos/CR-0012-full-graph-runtime-spike.md) remain `In progress`; independent review and the remaining qualification gates are open.

## Observations

| Boundary | Observed result |
|---|---|
| Sandbox and policy | `Ready`; exact effective policy revision `2356142798078066118`, hash `66b6f41515cdc406e51e9ae2282235f1ca02b110543d24d5c803f69addc6d330`, and zero attached OpenShell providers. The in-sandbox stage file hash was `cb5dda185437cdbe52617e777fc05ee3ad3e334f373ef6649d0bca75719f5555`. |
| Graph placement | `plan → retrieve → synthesize → verify` all reported PID 98, hostname `d9b841fdbafc`, and PID namespace `pid:[4026532708]` in the sandbox result. The baked worker imported and its code path was read-only. The result reports `verified=true`, two retained evidence items, and two claims citing those items. |
| Model and tools | Six actual HTTP model requests reached the credential-free stub: one plan, three retrieval, one synthesis, and one verification request. Only retrieval received the `read_fixture` catalog. Two allowed fixture reads returned `ownership` and `runbook`; an existing unadmitted fixture source was denied. |
| Network and cleanup | Direct TCP egress was denied; GET to the allowed relay path and POST to a wrong path were each denied at OpenShell L7. Deletion was accepted and the launcher observed the sandbox absent. |

The sanitized local artifacts are `/private/tmp/research-spike-aurora-5/observations/observations.json` (SHA-256 `a893fc3b6d08f833f71ea14f923858df0971b840d734304baa30f9a660967141`), its `result.json` (`168aafbe810e7e6cf5c6a1531e1f1655de58a317dc2863b8098d6790d408fa9d`), and `/private/tmp/aurora-model-audit-5.jsonl` (`0ce9c33ab40ef52b55de1a6b48228c65ff0705c6dcc14385ccd0c45bc1c861a9`). These temporary files are local observations, not retained release artifacts. The [version manifest](../../spikes/full_graph/version-manifest.json) pins the tested worker, Deep Agents, LangChain, OpenShell, fixture, model, and prompt versions. The separate [active-cancellation attempt](CR-0012-active-cancellation-2026-10-26.md) used this same worker image.

## Limits

This image was current for attempt 5; the later [attempt 6](CR-0012-full-graph-attempt-6-2026-10-26.md) rebuilt source and added live wrong-stage denial.

The stage header in this spike is copyable; it is not receiver-verified sender identity. [CR-0015](../change-requests/CR-0015-phase0-attempt-identity-readiness.md) and [CR-0016](../change-requests/CR-0016-phase1-sender-origin-proof.md) own the later application identity boundaries. This Docker-driver run does not prove Kubernetes CNI enforcement, the matched restricted-worker comparison, production model-gate cancellation, a real OpenAI call, or release CVE disposition. The [current exact-image local scan](CR-0013-local-image-scan-2026-10-26.md#current-cancellation-and-full-graph-image-preflight) found 48 high findings and blocks promotion under the proposed policy.
