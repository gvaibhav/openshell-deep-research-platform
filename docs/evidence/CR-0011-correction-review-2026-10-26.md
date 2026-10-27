# CR-0011: independent correction re-review

- **Date:** 2026-10-26
- **Reviewer:** `/root/milestone0_ci`, read-only sub-agent who did not author `eval/`.
- **Scope:** The corrected evaluator, 24-case synthetic draft, five original reproduced false-ready conditions, rubric/readiness behavior, and [CR-0011](../change-requests/CR-0011-matched-feasibility-evaluation.md).
- **Result:** The five original denial scenarios and timestamp rejection now pass. Two Important gaps remain; selection remains closed.

| Severity | Reproduced finding | Required correction |
|---|---|---|
| Important | With only the OpenShell candidate supplied and an observed uncited answer, the scorecard records a quality sentinel and `quality_threshold_met=false`, but global readiness becomes `incomplete` because another candidate is missing. `--allow-incomplete` exits 0, contrary to the evaluation guide's stated deny behavior. | Give an observed hard quality failure precedence over missing-candidate incompleteness, or make the draft CLI reject it; add a partial-run denial test. |
| Important | A constructed approved 20-case corpus with no prompt-injection case and all injection-resistance scores zero returned `ready_for_human_decision` at mean 85.7143. The scorer also requires all seven dimensions on every case, even when inapplicable. | Enforce preregistered category coverage and explicit per-case applicable dimensions, or record a reviewed exception that cannot look like a passing decision. |

The reviewer ran all 38 evaluator tests, Ruff, mypy, and `make check` on pinned Python 3.13.17; those passed. The current 24-case draft remains `incomplete` with no actual candidate runs. Human corpus/rubric approval, authorized ChatGPT and SEL-02 path assessments, matched restricted/OpenShell runs, blind artifact review, runtime proof, and the human selection decision remain unrun.

**Disposition:** Root assigned a second TDD correction to `/root/milestone0_eval`; re-review the new negative cases and keep [the paired ToDo](../todos/CR-0011-matched-feasibility-evaluation.md) open.
