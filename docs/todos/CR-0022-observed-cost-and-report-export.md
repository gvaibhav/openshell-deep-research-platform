# ToDo for CR-0022: Represent unknown cost and measured report export

- **ID:** CR-0022
- **Status:** In progress
- **Impact ID:** DR-FEAS-005
- **Phase:** Milestone 0, before observed matched runs
- **Accountable team:** Research evaluation and product owner (proposed)
- **Component paths:** `eval/cost_export.py`, `eval/schemas/`, `eval/scorecard.py`, `eval/blind_review/`, `eval/corpus/v1/rubric.json`, `eval/decision-record-template.md`, `eval/tests/`, `eval/README.md`, `docs/feasibility-and-market-assessment.md`
- **Requirement IDs:** SEL-01, SEL-05, RES-09
- **Change request:** [CR-0022](../change-requests/CR-0022-observed-cost-and-report-export.md)
- **Primary design:** [Milestone 0 implementation intake](../design/implementation-plan.md#6-milestone-0-implementation-intake)
- **Detailed impact analysis:** [Matched-pilot observation impact](../feasibility-and-market-assessment.md#matched-evaluation-fairness-and-observation-impact)
- **Proposed component design:** [v3 matched-evaluation observation contract](../design/matched-evaluation-contract-v3.md)

## Tasks and proof

- [x] Red/green the isolated `eval/cost_export.py` local observation/coverage helper and schema with synthetic artifact bytes and per-cell corroboration bindings; obtain independent code review. This slice does not migrate the signed scorer or establish external evidence truth.

- [ ] Specify/version completed-cell cost and report-export observations, raw and labeled assembly, per-cell independent control corroboration, scorecard cost/export coverage, and rejection of earlier signed artifacts. Revise rubric measurement values/digest before approval and the evaluator guide.
- [ ] Write red tests for unknown cost with valid completed answer, observed zero, unavailable cost without reason/evidence, full-matrix partial/deferred/failed/missing total-null rule, abstention export, wrong/empty export artifact, unexpected denial, denied private export, missing independent corroboration, and signed cost/export mutation.
- [ ] Implement strict schema/scorer/binding propagation and explicit `cost_uncertainty_open`/human-disposition requirement when unavailable cost exists. Every completed cell has exactly one export object; use the v3 truth table and separately count eligible versus justified N/A cells. Preserve blind review separation: reviewers do not receive candidate cost or identity.
- [ ] Update evaluator examples and [human decision template](../../eval/decision-record-template.md) so the product owner sees observed subtotal, coverage, report-export outcomes/evidence, and signed uncertainty disposition; do not claim unknown is zero or a deferred answer is failed.
- [ ] Run focused tests, `make check`, lint/type/format, and independent review on pinned inputs. Record human cost uncertainty disposition and actual export evidence separately from local synthetic tests.

## Evidence and closure

The [read-only corpus review](../evidence/CR-0011-corpus-readiness-review-2026-10-26.md) is the intake finding. The [independent v3 design review](../evidence/CR-0021-0022-v3-design-independent-review-2026-10-26.md) requires the full-matrix accounting, export truth table/content match, and per-cell control corroboration above. The isolated fragment has [red/green evidence](../evidence/CR-0022-local-cost-export-tdd-2026-10-26.md) and [independent review](../evidence/CR-0022-local-cost-export-independent-review-2026-10-26.md): 24 focused tests pass after correcting the expected-denial denominator and timestamp precision findings. [Draft PR #1](https://github.com/gvaibhav/openshell-deep-research-platform/pull/1) carries this slice. Root also passed all 428 local tests, check/lint/type/lock gates on Python 3.13.17 after the corrections. Full signed contract migration/scoring, rubric revision before approval, human cost disposition, and observed export evidence remain pending. This pair remains **In progress**. Disable by withholding cost/export parity and SEL claims.
