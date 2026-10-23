---
name: job-authorization-review
description: Design or review job visibility and result authorization changes involving Okta groups, reader grants, reports, evidence, or job APIs.
---

# Job authorization review

Use for a change to admission, visibility, list/status/events, report/evidence reads, sharing, or revocation. Read the [visibility design](../../../docs/design/research-visibility.md), affected [requirements](../../../docs/requirements.md), and [contracts](../../../contracts/README.md).

- Keep the admitted execution/source policy immutable and the job access policy separately versioned. Derive tenant and subject from verified server-side identity. A job ID, group name, gateway role, or source token is not a reader grant.
- Build an allow/deny matrix for the submitter, current member of the **one selected exact Okta group**, active named reader when supported, unrelated same-tenant user, other tenant, removed group member, and revoked job audience. Exercise list pagination, status, SSE replay, report, evidence, retained snapshot, cancellation, and resharing as affected.
- For a private report, check the reader's current source and classification rights for **all approved private job inputs**, including uncited ones. Fail closed when a required entitlement cannot be confirmed. Apply the exact source check to evidence and snapshots.
- Update affected OpenAPI/JSON Schemas, examples, and server policy tests. Run `make check`; a schema fixture alone does not prove an API enforces the decision. Report live Okta/source integration cases as passed only with observed nonproduction evidence, otherwise as unrun.
- Deliver the contract diff, endpoint-by-principal matrix, positive and negative results, audit/revocation behavior, and any owner decision needed for a wider audience.
