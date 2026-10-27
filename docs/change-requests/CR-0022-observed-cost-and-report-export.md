# CR-0022: Represent unknown cost and measured report export

- **ID:** CR-0022
- **Status:** Open
- **Impact ID:** DR-FEAS-005
- **Phase:** Milestone 0, before observed matched runs
- **Accountable team:** Research evaluation and product owner (proposed)
- **Component paths:** `eval/schemas/`, `eval/scorecard.py`, `eval/blind_review/`, `eval/corpus/v1/rubric.json`, `eval/decision-record-template.md`, `eval/tests/`, `eval/README.md`, `docs/feasibility-and-market-assessment.md`
- **Requirement IDs:** SEL-01, SEL-05, RES-09
- **Primary design:** [Milestone 0 implementation intake](../design/implementation-plan.md#6-milestone-0-implementation-intake)
- **Detailed impact analysis:** [Matched-pilot observation impact](../feasibility-and-market-assessment.md#matched-evaluation-fairness-and-observation-impact)
- **Proposed component design:** [v3 matched-evaluation observation contract](../design/matched-evaluation-contract-v3.md)
- **Independent design review:** [Ranked cost/export handoff findings](../evidence/CR-0021-0022-v3-design-independent-review-2026-10-26.md)
- **Parent:** [CR-0011](CR-0011-matched-feasibility-evaluation.md) / [ToDo](../todos/CR-0011-matched-feasibility-evaluation.md)
- **Paired ToDo:** [Implementation and proof checklist](../todos/CR-0022-observed-cost-and-report-export.md)

## Impact and decision

The ChatGPT tester guide correctly says to mark unavailable usage/cost `unknown`, but completed candidate-run records require numeric `cost_usd`. Entering zero would fabricate an observation; deferring a completed answer would erase valid quality data. SEL-01 also calls for report-export evidence, while the rubric and candidate-run contract have no explicit export outcome. The [independent corpus review](../evidence/CR-0011-corpus-readiness-review-2026-10-26.md) identified both gaps. This changes the evaluator's measurement contract and decision record, not the production report API. Data class is synthetic/public; export artifacts remain in approved evaluator custody.

The target completed-cell contract represents cost as an **observed nonnegative amount with provenance** or **unavailable with bounded reason and evidence**. Measured zero is distinct from unavailable. Scorecard v5 shows required, completed, observed-cost, unavailable-cost, deferred, failed, and missing cell counts per candidate, an observed subtotal, and `total_cost_usd: null` unless **every required cell completed with observed cost**. Human cost uncertainty disposition is required before SEL when any cost is unavailable; machine readiness may still present an otherwise complete case to the human with an explicit unresolved-cost flag. Every completed cell, including denied-source cases, has one report-export outcome under the [truth table](../design/matched-evaluation-contract-v3.md#cost-and-report-export-observations). An `exported` claim binds the actual product method/event and retained artifact bytes plus independently checked answer/citation correspondence to the reviewed run. A correctly denied expected-denial case alone may use justified `not_applicable`; an unexpected denial fails quality, while a protected-content answer/export after expected denial is a control violation. The signed control review contains one independent cost/export corroboration row per completed candidate/case/run, and the witness freezes it. Report export is an SEL-01 decision input, not a citation-quality score.

## Accepted and denied behavior

- **Accept:** A completed ChatGPT quality run whose product did not expose incremental cost can be retained with unavailable cost, reason, and evidence; its answer still receives blind quality review. An exported report records its actual artifact and provenance. A measured `$0.00` remains a numeric observation with provenance.
- **Deny:** Unknown cost serialized as zero or a string; a partial, deferred, failed, or missing-cell subtotal displayed as full cost; a missing export field treated as success; an `exported` claim with an empty/wrong artifact or answer/citation mismatch; an unexpected denial treated as `not_applicable`; a private-denial answer/export treated as permitted; missing or self-asserted metric/export corroboration; or observations changed after control review and witness freeze. The human selection gate cannot imply cost or export parity from a file-upload quality result.

## Risk, dependencies, and disable path

The risks are a false cost advantage, a hidden export gap, and a post-review metric rewrite. Version changed candidate-run/raw/map/control/witness/scorecard contracts consistently after CR-0011 and CR-0024 stabilize; the unchanged packet-manifest and path-catalog shapes still require legacy referenced-artifact rejection. Revise rubric measurement **values/digest** before approval and the human decision template now. Keep source-permission and quality gates separate. Until schemas, scorer, independent control corroboration, negative tests, and review pass, mark observed cost/export parity unknown and withhold SEL. If a candidate cannot provide cost, the decision may proceed only under a separately recorded, owned human uncertainty or estimate disposition; no machine report substitutes an estimate for an observation.

## Closure gate

The paired ToDo records allow/deny tests, exact contract versions, local checks, independent review, and first observed cost/export evidence. This pair remains open until component behavior and proof pass; documents alone do not close it.
