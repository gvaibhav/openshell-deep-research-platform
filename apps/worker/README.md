# Sandbox research worker

Future Python entrypoint baked into an immutable OCI image and launched as the canonical process of one OpenShell sandbox per research stage. It runs the **Deep Agents graph inside the sandbox**. The process receives a non-secret attempt reference, authenticates to fetch its narrow [stage manifest](../../contracts/stage-manifest.schema.json), uses only that stage's approved model and tools, and sends structured evidence and events back out. A public worker never receives the full enterprise question or private source identifiers.

The worker must not perform an interactive OAuth browser flow, store vendor refresh tokens, expose an inbound HTTP service, or decide which resources it may access. Filesystem scratch is ephemeral; durable job state and evidence live in the control plane. See [research and evidence](../../docs/design/research-and-evidence.md) and [job lifecycle](../../docs/design/job-lifecycle.md).

