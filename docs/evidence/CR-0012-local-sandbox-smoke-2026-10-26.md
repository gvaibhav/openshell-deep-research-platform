# CR-0012 local OpenShell sandbox smoke — 2026-10-26

This is a **synthetic-only Docker smoke test**, not a full-graph result or a Kubernetes, provider, identity, or production security qualification. It supports [CR-0012](../change-requests/CR-0012-full-graph-runtime-spike.md) and its [paired ToDo](../todos/CR-0012-full-graph-runtime-spike.md).

## Pinned inputs and setup

- Gateway and CLI: OpenShell v0.1.5 macOS arm64 archives downloaded from the [official release](https://github.com/NVIDIA/OpenShell/releases/tag/v0.1.5) into an isolated `/private/tmp/openshell-v0.1.5` directory. Published SHA-256 checks passed: CLI archive `48d6f4b4a222dc0a120ee4d6a677cb931bcc57f9ac54aefb101588f99c9c7642`, gateway archive `8e6fd1b05999709a9042ec83fcd902e062507af3e817f28bcda181fb93b42e7a`.
- Docker daemon/client: 29.9.2 on local macOS; driver reported `openshell/docker 0.1.5 (protocol 1.0)`.
- Supervisor image: `ghcr.io/nvidia/openshell/supervisor@sha256:fabcd01f656e9d23df4386f82e80b4f48b90f3452d7d5c58889007643a069161`.
- Sandbox runtime image: `ghcr.io/nvidia/openshell/sandbox@sha256:e9adf9ecde328122414ad2ee8c6fc5d5b389e4cf168daf4357c46f5a77d55851`.
- Workload image: `python@sha256:e031123e3d85762b141ad1cbc56452ba69c6e722ebf2f042cc0dc86c47c0d8b3`.
- Gateway bound only to `127.0.0.1:17671`, used temporary state, a generated local launch-signing bundle, `image_pull_policy = "never"`, and the Docker driver. The CLI was passed the endpoint explicitly; the previously installed OpenShell 0.0.44 CLI and its `nemoclaw` registration were unchanged.
- The temporary gateway used `disable_tls = true` and `allow_unauthenticated_users = true` to support a disposable local test. It must not serve employee or enterprise data. These settings are not the proposed deployment configuration.

## Observed allow and deny cases

| Check | Command or observation | Result |
|---|---|---|
| Gateway ready | `curl http://127.0.0.1:17672/readyz` | `healthy`, version `0.1.5`, database healthy |
| Sandbox created | `openshell sandbox create --name drm0-smoke-1026 --from python@sha256:e031123e… --no-auto-providers --detach -- python -c 'import time; time.sleep(300)'` | Sandbox reached `Ready`; configuration admission `accepted` |
| Effective policy | `openshell policy get drm0-smoke-1026 --full -o json` | Version 1, hash `a45a8ff3564f00ae26cbd66f1131f37eedd8b54a66fbfec103d65a204c19c6e8`; filesystem rules present, no network allow rule |
| In-sandbox execution | `openshell sandbox exec drm0-smoke-1026 --no-login-shell -- python -c 'import os; print("INSIDE_SANDBOX uid=" + str(os.getuid()))'` | `INSIDE_SANDBOX uid=1000` |
| Direct network denial | An in-sandbox Python socket attempted TCP to `1.1.1.1:443` | Process exited 1 with `PermissionError: [Errno 13] Permission denied`; no success marker |
| Outer Docker network | `docker inspect` on the two disposable containers | Workload `NetworkMode=none`; supervisor `NetworkMode=host` |
| Cleanup | `openshell sandbox delete drm0-smoke-1026`, then `sandbox list -o json` and `docker ps` | Deletion accepted; later list empty and no matching running containers |

## Remaining CR-0012 proof

The full planner/retriever/synthesizer/verifier graph has not run in this sandbox. An approved model route and host-side credential relay, exact policy for that relay, provider receipt, stage identity denial, cancellation, restricted-worker comparison, and independent review are still pending. This Docker result says nothing about Kubernetes CNI enforcement or enterprise-source access.
