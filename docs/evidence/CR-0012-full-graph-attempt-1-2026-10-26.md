# CR-0012: first disposable full-graph attempt

- **Date:** 2026-10-26
- **Data:** Fixed synthetic Aurora fixture only; no source or model credential entered the worker.
- **Status:** Failed closed before a worker result. This is partial runtime evidence, not full-graph conformance.
- **Runtime:** Isolated local OpenShell CLI/gateway v0.1.5, Docker driver, loopback gateway `127.0.0.1:17671` with disposable unauthenticated local access. The installed 0.0.44 CLI and its registration were left untouched.
- **Worker:** Linux ARM64 development image `localhost/openshell-research-spike@sha256:dfb5a468c965c674ed7d97884b7939e4585e6fd2deb98606d2c0d1882c492aa0`; its Python base fails the proposed release CVE gate.

## Observed sequence

1. `spike-aurora-1` reached `Ready`. `sandbox get -o json` reported `configuration_admission.state=accepted`, policy version 2, hash `f0e2405d471a124b34af30f7d5aa2b15fbc127c110bae0d10267c560af56a3f8`, and one `model_relay` REST endpoint to `host.docker.internal:8765` allowing POST `/v1/chat/completions` from `/usr/local/bin/python3.13`. `policy get --full` reported status `Effective`. The generated file digest and OpenShell's canonical policy hash are different representations and were not compared for equality.
2. The synthetic stage manifest uploaded. A direct in-sandbox TCP connection to `1.1.1.1:443` failed with `PermissionError`, and the launcher recorded direct egress denied.
3. The worker `sandbox exec` failed before writing a result. Its actual error, reproduced in a second disposable sandbox, was `ModuleNotFoundError: No module named 'spike'`. Explicit nonsecret `PYTHONPATH=/opt/spike` did not fix it; listing `/opt` from the sandbox failed with `PermissionError`. The generated filesystem policy omitted the baked worker code path. Dynamic read grants to `/opt/spike` and `/opt` reported policy versions 3 and 4 loaded on the existing sandbox but did not make that sandbox's filesystem readable. A fresh sandbox with a complete initial policy is required for the next test.
4. The first launcher accepted delete and later observed the sandbox absent. The second diagnosis sandbox, `spike-aurora-2`, was also deleted and a subsequent `sandbox get` returned `sandbox not found`.

The sanitized first-attempt metadata remain under `/private/tmp/cr0012-live-20261026-1/observations/` on the test host. They are temporary local evidence, not a durable release record.

## Still open

Run a new image and sandbox with the corrected initial filesystem policy. Inspect parsed effective policy, admission state, exact model route, and provider absence; observe an approved model call and an allowed plus denied fixture tool call; deny wrong method/path requests on the allowed relay host; prove all four graph processes and cancellation/cleanup. A local Docker result cannot establish Kubernetes CNI behavior, authenticated model ingress, matched real-model quality/cost, or release CVE qualification. See the [independent review](CR-0012-independent-review-2026-10-26.md) and paired [ToDo](../todos/CR-0012-full-graph-runtime-spike.md).
