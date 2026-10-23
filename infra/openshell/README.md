# OpenShell integration

Target the same OpenShell release for the gateway, CLI, and SDK. The design baseline is v0.1.5; the local CLI was 0.0.44 when this scaffold was created. Use the [official installation and upgrade guidance](https://docs.nvidia.com/openshell/home) before creating a live sandbox.

The controller will use the [Python SDK](https://docs.nvidia.com/openshell/sdk/python) with a dedicated OIDC service principal to create, observe, and delete per-job sandboxes. The worker image must be pinned and contain Python, Deep Agents, MCP client dependencies, and the worker entrypoint. Build separate public and enterprise worker policy templates after the image's exact executable paths and endpoint set are fixed.

OpenShell network rules must be deny-by-default, use exact broker/model destinations, set inspected MCP endpoints to `enforcement: enforce`, and list the tested MCP protocol revisions. OpenShell checks MCP tool names but not tool arguments. For Kubernetes, verify the CNI actually enforces ingress and egress `NetworkPolicy`; the gateway creating a policy object is insufficient. [Network rules](https://docs.nvidia.com/openshell/how-it-works/policies/network-rules) · [Kubernetes setup](https://docs.nvidia.com/openshell/kubernetes/setup).

No policy YAML is shipped yet because an unverified placeholder policy could accidentally allow the wrong executable or route. The [deployment design](../../docs/design/deployment-and-operations.md) specifies validation gates before a policy is promoted.

