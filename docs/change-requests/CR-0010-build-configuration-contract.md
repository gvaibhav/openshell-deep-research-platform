# CR-0010: Validate build profiles and external input references

- **ID:** CR-0010
- **Status:** Open
- **Impact ID:** DR-BUILD-001
- **Phase:** Milestone 2 after the SEL-01/02/04/05 decision; target-specific deployment proof before first network-accessible deployment
- **Accountable team:** Application platform team (proposed)
- **Component paths:** .env.example, .gitignore, docs/design/implementation-plan.md, apps/dashboard/, apps/api/, services/controller/, services/broker/, services/model-gate/, packaging/, deploy/ (planned)
- **Requirement IDs:** OPS-01, OPS-03, OPS-12, OPS-13, RES-11
- **Primary design:** [Implementation plan](../design/implementation-plan.md)
- **Detailed design:** [Okta configuration handoff](../okta/requirements-and-design.md#5-configuration-contract-handed-to-platform-team), [delivery workflow](../../AGENTS.md#design-change-impact-gate)
- **Paired ToDo:** [Implementation and proof checklist](../todos/CR-0010-build-configuration-contract.md)

## Impact on the application

The repository has no configuration loader or application code. The new [input worksheet](../../.env.example) names the external values needed at later milestones, but those names are not yet enforced. A self-declared `RESEARCH_DEPLOYMENT_TARGET=local` cannot prove that a process is outside a cluster. Without an independent artifact/admission guard and a typed profile contract, fixture identity or model providers could reach a live deployment, or an incomplete live profile could silently fall back to a broader credential, route, or source.

## Change request

After the [selection gate](../design/implementation-plan.md#3-milestones-and-exit-evidence), implement one validated application configuration contract for `fixture`, `sandbox_spike`, `live_public`, and `enterprise` profiles. The earlier disposable spike harness is a separate artifact: it validates its own gateway/model inputs and resolves an approved model secret or workload identity only in its host-side relay, not in the worker. Read only nonsecret endpoints, dashboard sign-in/sign-out URIs, client IDs, the selected profile/advisory target, approved `secret_ref` or `workload_identity` mode, and the **matching credential or workload-identity reference** from the environment. A missing or mismatched reference fails; it never selects a broader identity. Resolve secret references in the trusted service that owns each credential; never give model, Okta, or source secrets to the browser or sandbox worker. Make profile-specific required fields explicit. Pin tenant/group mappings, source selectors, data-class policy, deployment choices, and release versions in reviewed manifests. `DEPLOYMENT_MANIFEST_PATH` is a worksheet/tooling pointer only; it cannot authorize a cluster, namespace, project, region, or release without independent manifest approval and digest verification. Bind proposed model provider/endpoint/ID/auth-reference inputs to a reviewed, release-pinned model-route catalog before readiness; those env values alone cannot authorize a route. Match dashboard/API origins and Okta redirects to the approved environment registration, and public-search provider/ref to a reviewed public route with no enterprise source credentials.

Package development fixture/spike providers in a separate development image and omit them from the release image. The release image rejects `fixture` and `sandbox_spike` regardless of the env target. Before live Phase 0, prove signed-digest admission with policy-as-code and a disposable cluster. Before each staging/production Kubernetes deployment, the selected cluster's admission requires an approved signed release digest and rejects development images regardless of declared profile or target. Any network-accessible live public VM verifies the approved signed release digest before starting containers. The environment target remains advisory configuration, not a security attestation.

## Required behavior

- **Accept:** A complete local `fixture` profile starts in the development artifact without external credentials. A local `sandbox_spike` uses synthetic identity and sources with only an approved real model behind the model gate. A complete `live_public` profile uses separately configured Okta dashboard and gateway controller/provisioner clients, an approved exact model route, and public-search settings; an `enterprise` profile adds only reviewed source manifests and source-owner-approved grants. The selected profile, release-image identity, reviewed route-catalog digest, and nonsecret configuration digest appear in startup/release evidence. VM release verification and selected-cluster admission produce separate observed deployment evidence when those targets are used.
- **Deny:** The release image refuses fixture/spike profiles even with `RESEARCH_DEPLOYMENT_TARGET=local`; policy-as-code/disposable-cluster tests, the selected cluster admission, and a network-accessible VM release verifier reject a development image even with `RESEARCH_PROFILE=live_public`. An incomplete live profile, raw secret in a credential-reference field, unsupported project-prefixed config key, unresolved or wrong-mode reference, mixed Okta issuer/audience/client role, unregistered dashboard origin or redirect/logout URI, unreviewed public-search route, unapproved deployment manifest, or unreviewed connector manifest prevents the affected operation. A different model ID on the same allowed host, a route not matching the reviewed endpoint/model/auth reference, or a data class or trace route above the catalog allowance is denied before upstream inference. No missing value triggers a silent fixture or broader-app-identity fallback.

## Risk and disable path

The primary risks are secret exposure, a development fallback reaching a live deployment, and an env-provided model route bypassing reviewed class/trace policy. Keep live profiles unavailable until image identity, the applicable VM or cluster deployment guard, configuration validation, route-catalog matching, and secret-reference resolution pass. If an unsafe value is detected, stop readiness, remove it from logs/artifacts, rotate any exposed credential through its owner, and continue only with a corrected release/configuration. Local fixture mode may continue in the development artifact without enterprise credentials.

## Dependency and closure gate

The plan awaits user approval and the selection gate. No service consumes `.env` yet. Keep this CR `Open` until the typed loader, secret-reference handling, reviewed release-pinned route catalog, independent release-image and deployment guards, profile allow/deny tests, documentation reconciliation, and first build evidence are complete. Record the selected cluster or VM's live guard proof before its first network-accessible deployment. The paired ToDo records implementation and proof; documentation and an example file alone do not verify this CR.
