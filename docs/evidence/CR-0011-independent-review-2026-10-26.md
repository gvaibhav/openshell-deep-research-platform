# CR-0011 independent principal-engineer review — 2026-10-26

Read-only review of the public/synthetic evaluator for [CR-0011](../change-requests/CR-0011-matched-feasibility-evaluation.md) and its [paired ToDo](../todos/CR-0011-matched-feasibility-evaluation.md). The reviewer made no edits. These findings are open until a red/green correction and re-review pass.

| Priority | Finding and observed consequence | Affected implementation |
|---|---|---|
| **Blocker** | A supplied `permission_probe` is ignored on a case without `forbidden_evidence_ids`. An observed `allowed` probe produced zero violations and `ready_for_human_decision`; with other candidates missing, `--allow-incomplete` returned 0. Parse every supplied probe, require a declared target, and block on an observed allow where access should have been denied. | `eval/scorecard.py` probe handling and candidate schema |
| **Important** | An answer on an expected abstention case, or an expected answer with no citations, can score ready/100 when reviewer scores are high. Make contradictory observed behavior and missing minimum evidence structurally blocking; semantic support still needs human review. | `eval/scorecard.py` behavior and citation checks |
| **Important** | Only three of 24 cases exercise prompt injection, but all seven rubric dimensions are scored for every case. Three zero injection-resistance scores dilute the overall mean by about 1.25 points. Preregister applicable dimensions and a category/sentinel gate before corpus approval. | `eval/scorecard.py`, `eval/corpus/v1/rubric.json`, evaluator design |
| **Important** | Empty `connector_paths` can still produce `ready_for_human_decision`, leaving SEL-02 unassessed. Require an evidenced ChatGPT read-only MCP/plugin path result or an explicit reviewed unavailable/deferred state. | Candidate-run schema, `eval/scorecard.py` readiness |
| **Important** | Static checks fail: Ruff I001 import ordering in `eval/scorecard.py` and `eval/tests/test_scorecard.py`; mypy rejects `max(Any | None)` in scorecard quality-margin calculation. | Eval code and tests |
| **Optional** | CLI timestamp fields accept arbitrary nonempty text such as `tomorrow`, although the JSON Schema requires timestamp format. Align CLI validation with the schema. | `eval/scorecard.py` provenance validation |

The reviewer ran 27 evaluation tests, root unittest discovery, and `make check`: these passed. The draft CLI returned `incomplete` with all three candidates missing; it exited 2 by default and 0 with `--allow-incomplete`. The reviewer reproduced the false-ready cases separately in memory. Corpus/rubric approval, real candidate runs, ChatGPT entitlement/connector assessment, human semantic review, and CR-0012 live runtime proof remain unrun. Keep SEL-01/02/04/05 closed.
