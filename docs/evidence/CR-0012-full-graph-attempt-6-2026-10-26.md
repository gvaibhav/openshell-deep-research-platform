# CR-0012: fresh wrong-stage denial and complete synthetic OpenShell graph

- **Date:** 2026-10-26
- **Data and model:** Fixed invented Aurora fixture and a credential-free local model stub on port 8768. No real OpenAI key, upstream call, or enterprise source was used.
- **Runtime:** Isolated local OpenShell CLI/gateway v0.1.5 with Docker driver at `127.0.0.1:17671`; disposable sandbox `spike-aurora-6`.
- **Worker image:** `localhost/openshell-research-spike@sha256:bbf9907a5422c836fb10cd1c3b83959f2aef997a5fad2e7f70bab68aeab3909a` on Linux ARM64. The host launcher and model stub source were frozen and the image rebuilt before this attempt; baked `model_stub.py`, `relay.py`, and `worker.py` hashes matched the host source.
- **Disposition:** The corrected launcher exited 0. [CR-0012](../change-requests/CR-0012-full-graph-runtime-spike.md) / [ToDo](../todos/CR-0012-full-graph-runtime-spike.md) remain `In progress` pending independent review and the matched runtime, model, and release gates.

## Ordered allow and deny observations

| Step | Observed result |
|---|---|
| Admission and effective policy | Sandbox reached `Ready`; exact loaded revision `14700312888497762367`, effective policy hash `93e8e46c73c17251e050fc858f230123a951e21343f451a0151cbb07cc4d6982`, zero attached providers, read-only baked code, and in-sandbox stage file SHA-256 `cb5dda185437cdbe52617e777fc05ee3ad3e334f373ef6649d0bca75719f5555`. Authored policy file SHA-256 was `bca1fbeffa6a01ff740d7dbb6346e33992f0b1a59e473ce5e2c5b7a5628db77f`. |
| Wrong expected stage before model | After stage file verification and **before** the admitted graph, the launcher executed the baked worker against that file with a deliberately wrong expected stage. It required worker exit 2 and the exact bounded `StageManifestError` marker, then checked the fresh host model audit was still empty. Structured observation fields are `wrong_stage_denied=true` and `wrong_stage_model_audit_unchanged=true`. This is stage consistency, not receiver-verified sender identity. |
| Other denials | A read of an existing unadmitted fixture ID was denied. Direct TCP egress was denied. GET to the otherwise allowed relay path and POST to a wrong path each returned OpenShell's bounded JSON 403 with `error=policy_denied`, `policy=model_relay`, and `layer=l7`; a generic upstream 403 no longer passes the launcher probe. |
| Admitted graph | The same sandbox then ran `plan → retrieve → synthesize → verify`; all four steps reported PID 99, hostname `26ab42da0994`, and PID namespace `pid:[4026532708]`. The result reported `verified=true`, two approved `read_fixture` calls (`ownership`, `runbook`), two retained evidence items and two cited claims. The host-only audit contained exactly six allowed fixture-model calls with the expected stage/tool sequence. |
| Cleanup | Deletion was accepted; the launcher observed sandbox absence and a separate `sandbox list --output json` returned an empty array. The fresh stub process was stopped after evidence collection. |

| Local artifact | SHA-256 |
|---|---|
| `/private/tmp/research-spike-aurora-6/observations/observations.json` | `d8da01f494b59f4f0accd9642a19537931b7d049d0957133caf33eece328752b` |
| `/private/tmp/research-spike-aurora-6/observations/result.json` | `ee38dc05de151e43e82d97e83567dd5b28d5ff175350d17c67d506454a25f55d` |
| `/private/tmp/aurora-model-audit-6-20261026.jsonl` | `0ce9c33ab40ef52b55de1a6b48228c65ff0705c6dcc14385ccd0c45bc1c861a9` |

The local files are disposable observations, not retained release artifacts. A [network-disabled current-image body check](../../spikes/full_graph/README.md#network-disabled-pinned-client-body-check) also passed six pinned Deep Agents/LangChain request shapes through the strict relay validator, reserving 58,852 microUSD under a 60,000 microUSD **synthetic example** cap with no key or external socket. Its output SHA-256 was `0504e7add39cb0cdfd67afa6071ad40caa9bfb8a69ff518ed0a9f1e763896f68`. The [version manifest](../../spikes/full_graph/version-manifest.json) records the exact code, image, model, prompt, fixture, and OpenShell inputs.

## Limits

This is a disposable local Docker-driver result. The stage header and data-class header remain copyable; [CR-0015](../change-requests/CR-0015-phase0-attempt-identity-readiness.md) and [CR-0016](../change-requests/CR-0016-phase1-sender-origin-proof.md) own later application sender and authorization proof. The matched restricted-worker/CNI comparison, approved real-model call and usage reconciliation, authenticated relay ingress, ChatGPT comparison, production Kubernetes policy, and release CVE gates remain open. The exact-image [local scan](CR-0013-local-image-scan-2026-10-26.md) found 48 high findings, so this development image is blocked for promotion under the proposed policy.
