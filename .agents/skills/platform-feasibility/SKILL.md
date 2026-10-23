---
name: platform-feasibility
description: Evaluate whether a custom internal research platform or a major expansion is justified using matched incumbent, restricted-worker, and OpenShell cases.
---

# Platform feasibility

Use for the first build decision or a material change in platform, source access, or research workflow. Read the [selection requirements](../../../docs/requirements.md#platform-selection-gate) and [matched pilot design](../../../docs/feasibility-and-market-assessment.md) before defining an experiment.

- Freeze approved public/synthetic cases, a human-reviewed quality and permission rubric, decision thresholds, and cost/latency measures **before** running candidates. Name each candidate's actual tenant entitlement, connectors, deployment mode, and version.
- Compare the approved ChatGPT Enterprise workflow, Replit when its rollout permits, a restricted Kubernetes worker, and a full Deep Agents graph **inside** OpenShell on the same cases and source permissions. Verify graph placement and denied egress rather than inferring them from a sandbox tool call.
- Record citation support, completeness, abstention, permission denial, latency, user effort, operating cost, and the four custom controls in the [architecture](../../../docs/architecture.md). Mark unavailable candidates or unapproved private-source cases deferred; public cases cannot prove private-source authorization.
- Deliver a scorecard with raw run IDs or reproducible fixtures, known differences between candidates, the exact unmet requirement, and a go/no-go or narrower-scope recommendation. State which live checks remain unrun.
