---
name: openshell-runtime-conformance
description: Qualify OpenShell sandbox execution, effective policy, provider attachment, and Kubernetes network enforcement after runtime or deployment changes.
---

# OpenShell runtime conformance

Use for a new cluster, worker image, gateway/supervisor/runtime release, sandbox policy or provider change, CNI change, or the first full-graph spike. Read the [deployment gates](../../../docs/design/deployment-and-operations.md#10-promotion-integration-gates), [topology decision](../../../docs/design/deployment-topology.md), and [research worker design](../../../docs/design/research-and-evidence.md).

- Identify the exact installed gateway, supervisor, runtime, Agent Sandbox controller, CLI/SDK, worker image, chart, policy, and provider-profile digests. Verify CLI syntax against that installed release; do not execute a recipe from a moving upstream branch by assumption.
- In an approved test environment, prove planner, retrieval/tool client, synthesis, and verifier processes run inside the **per-job** sandbox. Capture effective policy (`--full` on qualified CLI versions), loaded revision, provider receipt, and the expected stage-manifest boundary before the worker begins.
- Independently probe ingress and egress NetworkPolicy enforcement in the actual workspace namespace. Show one approved broker/model request works, an unapproved tool or destination fails, direct worker egress fails, and cross-tenant reachability is denied. Inspect sandbox deletion and cancellation cleanup.
- Deliver the pinned manifest, commands or test harness version, observed allow/deny results, logs without secrets, and any mismatch. If no live environment is available, produce the executable test plan and mark runtime claims unrun; static YAML or `make check` is not conformance evidence.
