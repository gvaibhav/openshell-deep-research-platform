# ToDo for CR-0009: Enforce design impact and implementation traceability

- **ID:** CR-0009
- **Status:** Open
- **Impact ID:** DR-PROC-001
- **Phase:** Repository workflow now; protected CI before the first executable build
- **Accountable team:** Repository maintainers (proposed)
- **Component paths:** AGENTS.md, README.md, docs/decisions/, docs/TODO.md, docs/change-requests/, docs/todos/, .github/pull_request_template.md, scripts/validate_repo.py, future CI configuration
- **Requirement IDs:** OPS-12
- **Change request:** [CR-0009](../change-requests/CR-0009-design-impact-traceability.md)
- **Design baseline:** [ADR 0002](../decisions/0002-design-impact-traceability.md)

## Implementation and proof checklist

- [x] Add the impact-analysis, per-impact CR/ToDo, document synchronization, and as-built closure workflow to AGENTS.md and the pull request template.
- [x] Link each source-authentication impact pair from ADR 0001, the relevant component design, README, and the index; record this process impact in ADR 0002.
- [x] Add structural validation for pair naming, IDs, allowed matching status, reciprocal links, and direct design/README/index backlinks to `make check`.
- [x] Record positive and negative validator evidence for a valid pair, an orphan or mismatched pair, an invalid status, and a missing required backlink; record independent review disposition.
- [ ] Run `make check` in protected pull-request CI before the first executable build and make failure block merge.
- [ ] Confirm the first implementation pull request cites its pair, requirements, proof, and as-built design reconciliation.

## Completion evidence

- **Pull request and artifact versions:** [Draft PR #1](https://github.com/gvaibhav/openshell-deep-research-platform/pull/1) is open; repository changes are not merged and protected enforcement remains absent. The [checkpoint handoff](../handoffs/milestone0-protected-ci-checkpoint.md) records current local checks, secret review, and the exact required-check owner path.
- **Accepted and denied cases:** Use the [CR required behavior](../change-requests/CR-0009-design-impact-traceability.md#required-behavior) as the criterion. A temporary one-pair repository fixture passed with zero errors; mismatched status, missing index backlink, invalid status, and orphaned CR fixtures each produced the expected validator error on 2026-10-23. The invalid-status case produced errors for both files.
- **Local check:** `make check` passed on 2026-10-23: 16 JSON Schemas, 21 examples, 11 OpenAPI operations, 53 Markdown files, 102 Mermaid fences, and 9 CR/ToDo pairs. `git diff HEAD --check` passed. A read-only principal engineer review of the current design/workflow diff reported no Blocker or Important findings; its remaining gates are protected CI and a first implementation-PR demonstration.
- **Protected CI and implementation intake:** Pending before the first executable build.
- **Closure:** Keep both records `Open` until the required evidence and CI gate pass. Then reconcile the workflow, requirement, ADR, README, and index; set both statuses to `Verified` together while retaining their links.
