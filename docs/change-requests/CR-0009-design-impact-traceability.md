# CR-0009: Enforce design impact and implementation traceability

- **ID:** CR-0009
- **Status:** Open
- **Impact ID:** DR-PROC-001
- **Phase:** Repository workflow now; protected CI before the first executable build
- **Accountable team:** Repository maintainers (proposed)
- **Component paths:** AGENTS.md, README.md, docs/decisions/, docs/TODO.md, docs/change-requests/, docs/todos/, .github/pull_request_template.md, scripts/validate_repo.py, future CI configuration
- **Requirement IDs:** OPS-12
- **Primary design:** [ADR 0002](../decisions/0002-design-impact-traceability.md)
- **Detailed design:** [Development workflow](../../AGENTS.md#design-change-impact-gate)
- **Paired ToDo:** [Implementation and proof checklist](../todos/CR-0009-design-impact-traceability.md)

## Impact on the repository

The former global ToDo listed component gaps but did not give each impact its own change obligation and proof record. Without an impact matrix, direct design and README backlinks, and implementation closure evidence, architecture, design, and application logic can diverge silently.

## Change request

Require a surface-by-surface impact analysis for each design change, one CR and paired ToDo for every distinct impact, revisions to affected existing documents in the same design change, and direct durable links from the primary design, README, and index. Require an implementation slice from an existing baseline design to create a pair before code if it lacks one. Check structural traceability locally and in protected CI before executable builds; use review to judge semantic completeness and as-built agreement.

## Required behavior

- **Accept:** A design or baseline implementation slice with an impact ID, exactly one matching CR/ToDo pair, current affected documents, required backlinks, and recorded verification evidence passes its applicable review and repository checks. An implementation pair reaches `Verified` only with named code/configuration and positive/negative proof; a documentation-only pair reaches it after reviewed document checks.
- **Deny:** An orphan, mismatched ID or status, missing required backlink, or untracked affected surface fails the check or review. A documentation-only edit cannot mark an implementation pair `Verified`.

## Risk and disable path

A passing structural check can create false confidence if reviewers do not identify a real impact or reconcile application behavior. Keep the human impact review and independent material-change review as required gates. If validation is unavailable or misclassifies a legitimate pair, fix the validator and rerun it before merge; do not silently bypass the traceability gate. This change has no production runtime path to disable.

## Dependency and closure gate

The current repository has no protected CI pipeline. The local validator and linked pair records can be reviewed now, but this CR remains `Open` until protected CI runs the check before executable code is merged and the paired ToDo records positive and negative check evidence plus review disposition. Preserve the links after verification or withdrawal.
