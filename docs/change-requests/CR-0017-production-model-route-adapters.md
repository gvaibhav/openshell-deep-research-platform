# CR-0017: Implement reviewed provider adapters in the production model gate

- **ID:** CR-0017
- **Status:** Open
- **Impact ID:** DR-MODEL-002
- **Phase:** Milestones 2–3 after a positive SEL-01/02/04/05 decision; before live public model traffic
- **Accountable team:** Model-platform and application teams (proposed)
- **Component paths:** Planned `services/model-gate/`, `services/model-gate/providers/`, `config/model-routes/`, and `contracts/internal/model-route.schema.json`; exact paths and version selected before code
- **Requirement IDs:** RES-11, NFR-07, IAM-05, OPS-10
- **Primary design:** [Production provider route and impact analysis](../design/research-and-evidence.md#production-provider-adapter-and-route-catalog-impact)
- **Paired ToDo:** [Implementation and proof checklist](../todos/CR-0017-production-model-route-adapters.md)

## Current and target behavior

The disposable [CR-0014](CR-0014-local-model-provider-router.md) host relay will pin OpenAI `gpt-5.6-sol` for a synthetic comparison. It is neither a production model gate nor a reusable application credential boundary. The application has no running model service or route catalog. The existing [RES-11](../requirements.md#53-research-quality-and-evidence) design already requires a server-held route alias, exact upstream model/body, class, trace, and budget decisions; the user additionally wants a provider-neutral route so a future vendor switch does not rewrite worker code.

Implement a trusted model gate with a versioned, reviewed route catalog and an explicit provider adapter interface. The first approved adapter may target OpenAI `gpt-5.6-sol`; a later provider needs a new catalog revision, canonical request/response and usage mapping, pricing basis, credential reference, allow/deny tests, and owner review. The worker sends only an internal route alias and approved native-compatible body to the gate; it never chooses an arbitrary provider, endpoint, model, or credential. The catalog pins each admitted job's immutable route snapshot; a changed provider or newly cleared class uses a fresh reviewed snapshot and attempt, never silent in-flight fallback. [CR-0015](CR-0015-phase0-attempt-identity-readiness.md) owns per-attempt readiness, while this pair owns the full route, request, response, classification, and metering behavior.

## Required behavior

- **Accept:** A ready current attempt with an approved class uses one exact catalog route. The adapter constructs a text/body-schema-approved upstream request with a gate-held credential, enforces hard concurrent request/token/estimated-cost reservations and response bounds, normalizes only approved output/usage, and records pinned model/prompt/price/trace metadata. A reviewed second adapter can be selected by a new route revision without changing worker credential custody or the worker-facing contract.
- **Deny:** Unknown adapter/provider, arbitrary or changed host/model/body, worker-supplied upstream credential, unreviewed tool/file/URL/multimodal field, over-class prompt, missing or pre-ready attempt, stale generation, unbounded or over-budget request, uncertain usage refund, and unapproved automatic fallback before upstream dispatch. A switch of catalog route for an active attempt is denied.

## Dependencies, risk, and disable path

Depends on a positive SEL decision, [CR-0015](CR-0015-phase0-attempt-identity-readiness.md), an approved model/data-class/trace/retention and price policy, secret-manager or workload-identity custody, and qualified OpenShell ingress. An adapter error could leak sensitive context or bypass spend caps. Disable the route in the trusted catalog, fence its active attempts and upstream requests, retain conservative reservations, and roll forward or back only with a reviewed immutable route revision and fresh attempts. No real model key is placed in the worker or release image.

## Closure gate

Before dependent code, version the internal catalog/adapter contract and valid/denied fixtures. The paired ToDo must link implementation PRs, pinned provider/SDK/model/prompt/price versions, exact-class and request-shape proof, concurrent/stream budget and cancellation evidence, real nonproduction allow/deny tests, CVE/SBOM coverage, and independent model/security review. The synthetic host relay and an endpoint-bound OpenShell provider alone do not close this pair.
