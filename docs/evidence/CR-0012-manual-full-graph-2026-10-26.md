# CR-0012: interim manual full-graph and route observations

- **Date:** 2026-10-26
- **Scope:** Disposable synthetic-only local OpenShell v0.1.5 Docker gateway; worker image `localhost/openshell-research-spike@sha256:dfb5a468c965c674ed7d97884b7939e4585e6fd2deb98606d2c0d1882c492aa0` and credential-free fixture model. This development image fails the proposed CVE release gate.
- **Status:** Partial live proof. It predates the independent-review tool-call and launcher corrections and does not close [CR-0012](../change-requests/CR-0012-full-graph-runtime-spike.md).

## Observed

1. A **new** sandbox `spike-opt-1` was created with an initial filesystem policy granting read access to `/opt` and `/opt/spike` and an exact REST model route to `host.docker.internal:8765`. `sandbox create` reported `Ready` and `configuration_admission.state=accepted`, canonical policy hash `c492998b73171a8874919f71b79fae915ec18802bcf98537c4ce9758f3439473`. With explicit nonsecret `PYTHONPATH=/opt/spike`, `import spike.worker` succeeded. Adding read paths to an already running sandbox had not fixed the preceding attempt.
2. The default filtered `sandbox upload` made `/work/stage.json` a **directory** containing `stage.example.json`; the worker failed with `IsADirectoryError`. `sandbox upload --no-git-ignore` to `/work/stage-v2.json` made a regular file. The corrected manifest path then let the old image's real Deep Agents/LangGraph worker run: its result reported `verified=true`, stages `plan → retrieve → synthesize → verify`, two retained evidence items, and two cited claims.
3. All four stage markers reported PID 94, hostname `d5c17e8ea189`, and PID namespace `pid:[4026532708]`. Docker inspection showed `d5c17e8ea189` was the actual `spike-opt-1` worker container, while its separate supervisor container was `647e7c370972`. This supports in-worker graph placement for this image.
4. From `/usr/local/bin/python3.13` in that sandbox, GET `/v1/chat/completions` and POST `/v1/wrong-path` on the otherwise allowed relay host each returned HTTP 403 with `error=policy_denied`, `policy=model_relay`, and `layer=l7`. The fixture server itself would answer those requests with different statuses, so these are observed OpenShell REST rule denials. The successful graph used the permitted POST route.
5. Deletion of `spike-opt-1` was accepted and a subsequent `sandbox get` returned `sandbox not found`.

The synthetic result and two-request probe script remain only in `/private/tmp/cr0012-manual-result.json` and `/private/tmp/cr0012-route-probe.py` on the test host. No credential, private source, or real model was used.

## Still open

The old model stub did not request `read_fixture`; this run does not prove an allowed or denied source-tool argument, actual model-call accounting under tool use, copied identity denial, cancellation, provider absence, or the revised launcher's exact policy and cleanup checks. A corrected image and updated tool-calling stub must rerun the whole path. A Docker sandbox does not prove Kubernetes CNI, real-model relay ingress, matched candidate quality/cost, or final-image CVE disposition. See the [independent review](CR-0012-independent-review-2026-10-26.md) and [paired ToDo](../todos/CR-0012-full-graph-runtime-spike.md).
