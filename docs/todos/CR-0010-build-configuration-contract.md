# ToDo for CR-0010: Validate build profiles and external input references

- **ID:** CR-0010
- **Status:** Open
- **Impact ID:** DR-BUILD-001
- **Phase:** Milestone 2 after the SEL-01/02/04/05 decision; target-specific deployment proof before first network-accessible deployment
- **Accountable team:** Application platform team (proposed)
- **Component paths:** .env.example, .gitignore, docs/design/implementation-plan.md, apps/dashboard/, apps/api/, services/controller/, services/broker/, services/model-gate/, packaging/, deploy/ (planned)
- **Requirement IDs:** OPS-01, OPS-03, OPS-12, OPS-13, RES-11
- **Change request:** [CR-0010](../change-requests/CR-0010-build-configuration-contract.md)
- **Design baseline:** [Implementation plan](../design/implementation-plan.md)

## Implementation and proof checklist

- [x] Create a tracked nonsecret `.env.example`, an ignored owner-readable `.env`, and an ignored `.secrets/` path.
- [x] Record the staged build plan, impact analysis, and direct CR/ToDo links in the primary design, README, and index.
- [ ] Record user approval before spike code starts; complete the SEL-01/02/04/05 selection decision before full dashboard/API code starts.
- [ ] Implement a typed post-selection loader for `fixture`, `sandbox_spike`, `live_public`, and `enterprise`; treat `RESEARCH_DEPLOYMENT_TARGET` as advisory only.
- [ ] Package fixture/spike providers only in a development artifact; make the release image reject both profiles independently of env target. Test signed-digest admission as code and in a disposable cluster; verify the signed release digest before a network-accessible live public VM start and enforce it on each selected staging/production cluster before deployment.
- [ ] Resolve model, Okta, and source credentials only from the owning service's approved secret or workload-identity reference. Require the reference matching the selected auth mode; never accept browser or worker secret values as configuration authority.
- [ ] Bind model provider/endpoint/ID/auth-reference inputs to a reviewed pinned route catalog, including class and trace/retention policy; deny wrong-model-on-same-host and over-class requests before upstream inference.
- [ ] Test valid local fixture startup and denial of incomplete live configuration, wrong issuer/audience/client separation, unregistered dashboard/API origins or sign-in/sign-out redirects, unreviewed public-search route, unresolved or wrong-mode refs, raw secrets in reference fields, unsupported project-prefixed keys, and unreviewed connector/deployment manifests.
- [ ] Test a release image with `fixture` plus target=`local`, and a development image declaring a live profile in disposable/selected Kubernetes admission and VM deployment; all deny. Record admission or verifier policy and image-signature/digest evidence.
- [ ] Record the first implementation pull request, configuration schema/version, allow/deny results, and release evidence; reconcile the plan and component guides with actual behavior.

## Completion evidence

- **Pull request and artifact versions:** Pending.
- **Allow/deny evidence:** Pending. Use the paired [CR required behavior](../change-requests/CR-0010-build-configuration-contract.md#required-behavior) as the criterion and link versioned observed results here.
- **Local document check:** `make check` passed on 2026-10-23: 16 JSON Schemas, 21 examples, 11 OpenAPI operations, 56 Markdown files, 103 Mermaid fences, and 10 CR/ToDo pairs. `git diff --check` passed. These checks validate structure, not the future image, profile, or OAuth behavior.
- **Live qualification:** Pending; no service consumes the template yet.
- **Closure:** Keep both records `Open` until implementation, tests, and as-built design reconciliation pass. Then mark both `Verified` together and retain the links.
