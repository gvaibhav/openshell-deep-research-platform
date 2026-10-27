# CR-0014: Route the disposable model spike through an explicit provider adapter

- **ID:** CR-0014
- **Status:** In progress
- **Impact ID:** DR-MODEL-001
- **Phase:** Milestones 0–1 synthetic spike; production model gate remains separately gated
- **Accountable team:** Research worker and model-platform teams (proposed)
- **Component paths:** `spikes/full_graph/spike/relay.py`, provider helper and tests under `spikes/full_graph/`, `spikes/full_graph/relay-route.example.json`, `.env.example`, spike guide
- **Requirement IDs:** SEL-04, RES-01, RES-11, NFR-01
- **Primary design:** [Implementation plan, local model route](../design/implementation-plan.md#7-local-model-route-impact-analysis)
- **Operational handoff:** [Deployment and operations](../design/deployment-and-operations.md#build-security-and-cve-gate)
- **Paired ToDo:** [Implementation and proof checklist](../todos/CR-0014-local-model-provider-router.md)

## Current and target behavior

At intake, the disposable relay accepted a generic HTTPS Chat Completions URL and either a host file reference or GCP ADC token. Its route did not name a provider and could not consume the user's requested host-side OpenAI environment variable. The user selected OpenAI `gpt-5.6-sol` for the synthetic comparison and wants a provider-neutral adapter seam for a later switch. [OpenAI's model page](https://developers.openai.com/api/docs/models/gpt-5.6-sol) names that exact ID and Chat Completions support; the [API reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create) gives the exact HTTPS route.

Add an explicit provider ID and registered adapter interface to the **host-side disposable relay**. The OpenAI adapter pins `https://api.openai.com/v1/chat/completions` and `gpt-5.6-sol`; it may read `RESEARCH_OPENAI_API_KEY` from only the relay host process environment during a local synthetic run. Keep the worker's placeholder header separate, strip it, and never pass the real key to OpenShell, an image, a stage manifest, logs, CI, or `.env`. **Every launcher-spawned OpenShell CLI process must receive an explicit nonsecret environment allowlist** so an operator's exported key cannot be inherited by those children; test this with a synthetic canary. A later provider switch must register an adapter, exact endpoint/model/body/price and data-class route, tests, and a reviewed versioned decision; it must not silently fall back to an arbitrary OpenAI-compatible URL. Application and enterprise deployments continue to use the trusted server-side model gate and approved secret-manager or workload-identity reference under [RES-11](../requirements.md#53-research-quality-and-evidence).

## Required behavior

- **Accept:** An explicitly selected, approved OpenAI route sends a **canonical text-only Chat Completions body constructed from checked role-specific message and tool fields** to the exact upstream endpoint using a host-held key, with the exact model ID and bounded request/cost reservation. The same worker/model-gate interface can select a different registered provider through a new reviewed route without changing worker source or credential custody. A local fake upstream proves key isolation and header replacement before any real API call.
- **Deny:** Missing/empty key, unsupported provider, mismatched model or endpoint, unreviewed top-level or nested message/tool field, image/URL/file content part, malformed `tool_calls`, over-budget request, or an attempt to pass the key into a launcher CLI child, worker, manifest, image, or CI artifact fails before upstream contact with a bounded error. A real provider call and any public/private data are denied until the model route, data class, budget, and host ingress path are approved and observed.

## Dependencies, risk, and disable path

This is a model-route refinement inside the already approved [CR-0012](CR-0012-full-graph-runtime-spike.md) spike; it does not authorize the production model gate or alter Okta/source token boundaries. A host environment value can be inherited by host child processes, so the disposable relay must not spawn unreviewed children, print environment or exception bodies, or run in shared CI with a real key. Prefer the existing secret file/reference or workload identity for a managed deployment. Disable by not selecting the OpenAI adapter and unsetting `RESEARCH_OPENAI_API_KEY`; keep the credential-free fixture stub for deterministic tests. This pair remains `In progress` until code, tests, route review, and an approved nonproduction real-model observation are linked in its ToDo.
