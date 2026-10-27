# CR-0024: Bind the blind packet answer to the candidate answer

- **ID:** CR-0024
- **Status:** In progress
- **Impact ID:** DR-FEAS-007
- **Phase:** Milestone 0, before any observed packet distribution or scoring
- **Accountable team:** Research evaluation and evaluator custody (proposed)
- **Component paths:** `eval/blind_review/tool.py`, `eval/binding.py`, `eval/schemas/`, `eval/blind_review/tests/`, `eval/tests/`, `eval/blind_review/README.md`, `eval/README.md`
- **Requirement IDs:** SEL-01, SEL-05, RES-09
- **Primary design:** [v3 matched-evaluation contract](../design/matched-evaluation-contract-v3.md)
- **Detailed impact analysis:** [Matched-evaluation packet integrity impact](../feasibility-and-market-assessment.md#matched-evaluation-packet-answer-integrity-impact)
- **Finding:** [Independent v3 design review](../evidence/CR-0021-0022-v3-design-independent-review-2026-10-26.md)
- **Parent:** [CR-0011](CR-0011-matched-feasibility-evaluation.md) / [ToDo](../todos/CR-0011-matched-feasibility-evaluation.md)
- **Paired ToDo:** [Implementation and proof checklist](../todos/CR-0024-blind-packet-answer-integrity.md)

## Impact and decision

The earlier v2 packet utility accepted separately hashed `raw_answer` and `packet_answer` strings that could differ. A reviewer could therefore score a repaired packet while the actual candidate answer was wrong. The signed bundle faithfully bound both strings but did not establish that the scored answer was the observed one. This candidate-output-to-blind-review defect has a local exact-byte correction and [independent code review](../evidence/CR-0011-0024-final-custody-independent-review-2026-10-26.md); the separate original-run and witness gates remain under CR-0011/0025.

For this wholly synthetic/public pilot, the two completed-cell strings must have **identical UTF-8 bytes, without normalization, redaction, or claim editing**. Preparation rejects a mismatch; unblinding and scorecard binding independently recheck equality against the exact signed raw observation, screened packet, map, and control-review raw-answer digest. The independent control reviewer still corroborates the raw answer against the retained candidate run; local equality cannot prove that source event. No schema field is added for the v2 correction, but the equality rule becomes a required cross-field validation. The proposed v3 contract inherits it and rejects older signed bundles for observed readiness.

## Accepted and denied behavior

- **Accept:** A completed synthetic/public cell whose raw answer and reviewer packet answer are byte-identical, pass identity/source screening, and match the independently retained raw run can enter blind review after the other CR-0011 gates pass.
- **Deny:** A wrong raw answer replaced by a correct packet answer, a packet with edited citations or claims, a resigned mismatched raw/map/packet/control bundle, or an answer with candidate-identifying content presented to a blind reviewer. A label leak may be quarantined and represented as a separately evidenced noncompleted cell for a new approved run; it never becomes a scored success by redaction. Unauthorized source disclosure is a control violation and cannot be hidden as a deferral.

## Risk, dependencies, and disable path

Strict equality may reduce evaluable cases when a product includes its identity in the answer. Record the original attempt in restricted custody, retain the reason and independent control evidence, and rerun only under approved blind-safe inputs; do not silently discard a poor answer or change a completed result to improve its score. If comparable blind review cannot be obtained, report that arm/cell as deferred and keep selection incomplete. The v2 prepare and signed verification paths passed the local negative tests and independent review. Keep packet distribution, unblinding for selection, scorecard readiness, and SEL use closed under CR-0011/0021/0025 until their remaining external gates pass. No production source authorization changes.

## Closure gate

The [paired ToDo](../todos/CR-0024-blind-packet-answer-integrity.md) records four red-first tests passing in the local v2 prepare and signed verification paths, 167 focused tests, and [independent read-only code review](../evidence/CR-0011-0024-final-custody-independent-review-2026-10-26.md) with no remaining scoped finding. The exact-byte correction passed local code and independent review, but this pair remains **In progress** until the implementation PR and protected CI result are recorded against immutable code. External candidate-run truth, organizational witness custody, packet distribution, and observed selection remain closed under CR-0011/0021/0025; local review does not satisfy those gates.
