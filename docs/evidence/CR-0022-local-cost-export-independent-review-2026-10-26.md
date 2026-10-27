# CR-0022 isolated cost/export independent review

**Disposition:** No remaining scoped Blocker or Important finding after corrections. The unused helper is ready for its next local integration-planning stage, not observed scoring, packet distribution, or SEL. Reviewer: `/root/cost_export_review`, read-only; root transcribed the returned evidence. Requirements: SEL-01/05 and RES-09. Data: synthetic fixtures and retained synthetic bytes only.

## Scope and reviewed inputs

Reviewed [the helper](../../eval/cost_export.py), [local v1 schema](../../eval/schemas/cost-export-observations.schema.json), [tests](../../eval/tests/test_cost_export.py), [v3 target design](../design/matched-evaluation-contract-v3.md#cost-and-report-export-observations), [CR-0022](../change-requests/CR-0022-observed-cost-and-report-export.md) / [ToDo](../todos/CR-0022-observed-cost-and-report-export.md), and synchronized documentation. Python 3.13.17 was used from the existing pinned environment. The helper leaves candidate-run v2, scorecard v4, signed custody, and the rubric unchanged. It authenticates no supplied assertion.

The concurrent CR-0011 output-writer correction is outside this review. Reviewed exact file SHA-256 values:

| File | SHA-256 |
|---|---|
| `eval/cost_export.py` | `7aa15d479fdf72974cb96a2ce0495ad0f80e43b990584c796a1349b5339fe5a7` |
| `eval/schemas/cost-export-observations.schema.json` | `f03299abbedf40bc40479df59bb4cfb250e2bc5e1eac0e821f66881fcef6632b` |
| `eval/tests/test_cost_export.py` | `d5c1c95087a3f1c18e973ee826cf3aedb49ec5b84b6b745e6bac1d47e470803d` |

## Findings and correction dispositions

- **Important, corrected:** A correctly denied expected-denial cell accepted failed/unsupported/unavailable/not-attempted export states and entered the export-eligible denominator with no behavior mismatch. This could turn correct permission behavior into a product gap. The helper now requires justified `not_applicable` for that cell and excludes it from the denominator. Four branch regressions failed before the correction and pass afterward.
- **Optional correctness edge, corrected:** More than six fractional timestamp digits were accepted and truncated during parsing; `.1234569Z` followed by `.1234561Z` could appear ordered. Schema and runtime now reject submicrosecond precision. The regression failed before correction and passes afterward; valid six-digit timestamps and cross-offset ordering remain accepted.

The implementer's [TDD evidence](CR-0022-local-cost-export-tdd-2026-10-26.md) records both review reproductions, the earlier missing-module red phase, and a Decimal-context correction.

## Independent checks

- All **24 focused tests** passed.
- Seventeen additional allow/deny probes covered missing event/method/time/correspondence/allocation evidence, wrong answer/citation digests, Boolean version, invalid Unicode, and protected disclosure.
- All 125 three-cell combinations of observed/unavailable/deferred/failed/missing states matched independent coverage expectations.
- A 128-cell mixture of large, subnormal, and decimal amounts matched an independent `Fraction` calculation.
- An exhaustive 108-combination export truth-table oracle passed after correction, as did six over-precision timestamp-position denials and valid cross-offset ordering.
- `make check` passed (28 schemas, 144 Markdown files, 25 pairs at review time); focused Ruff lint/format, mypy, and diff whitespace checks passed.

## Limits and next gates

The helper binds supplied object digests, cell/run IDs, and retained artifact bytes. It cannot establish reviewer independence, product-event authenticity, source permissions, native extraction, or semantic correspondence. Rejecting reuse of the exact answer reference is a local alias guard, not general copied-answer detection: different references and consistent assertions can pass, and a legitimate native text export may equal answer bytes. Unexpected denial remains a behavior mismatch even if an actual export observation is recorded; the helper emits no quality, export-parity, or readiness decision.

Signed control corroboration, the coordinated CR-0021/0022/0025 version migration, approved input/rubric bytes, product-native evidence, human uncertainty/export dispositions, and matched runs remain open. Keep CR-0022 **In progress**. Disable/rollback by leaving this helper unused; no distribution or production path depends on it.
