# CR-0023: Correct draft corpus fairness and coverage before distribution

- **ID:** CR-0023
- **Status:** In progress
- **Impact ID:** DR-FEAS-006
- **Phase:** Milestone 0 selection input, before any candidate run
- **Accountable team:** Research evaluation with product and security approval (proposed)
- **Requirement IDs:** SEL-01, SEL-02, SEL-05, RES-09
- **Data class:** Wholly synthetic
- **Component paths:** `eval/corpus/v1/`, focused corpus tests, `eval/README.md`, `docs/feasibility-and-market-assessment.md`, `README.md`, `docs/TODO.md`
- **Primary design:** [Implementation plan](../design/implementation-plan.md#6-milestone-0-implementation-intake)
- **Impact analysis:** [Draft corpus fairness and coverage impact](../feasibility-and-market-assessment.md#draft-corpus-fairness-and-coverage-impact)
- **Parent selection work:** [CR-0011](CR-0011-matched-feasibility-evaluation.md) / [ToDo](../todos/CR-0011-matched-feasibility-evaluation.md)
- **Paired ToDo:** [Implementation and proof checklist](../todos/CR-0023-corpus-fairness-and-coverage.md)

## Current versus target behavior

The unapproved 24-case synthetic pack includes an evaluator ambiguity in the sole-causation abstention case, a temporal canary question that can conflate a pause and a later flag disablement, an approval citation anchor that omits the requested time, and injection questions or source text that announce the attack. Two public region records are unused. These weaknesses can bias a matched product comparison even if the scorer correctly verifies its signed inputs. The [independent read-only corpus review](../evidence/CR-0011-corpus-readiness-review-2026-10-26.md) also found exact-quote scoring and observed-metric/export contract issues; those are separately tracked in CR-0021/0022 and are dependencies for scored use.

The target is a revised, still **draft** 20–30-case pack with unambiguous evaluator coding, time-aware support, uncued prompt-injection tasks, and no unused record in the source pack. Cue checks cover the **entire candidate-visible projection and MCP search/fetch metadata**, including source ID, origin, title, and text; neutralizing only the question and source text is insufficient. Keep the existing case/source/rubric contract shapes and case-specific source permissions; revise the bytes and their SHA-256 pins before independent product/security approval. An evaluator-only review packet must identify the exact revised raw and canonical digests, each case's permitted and forbidden IDs, behavior, anchors, ambiguity, and sentinel without becoming a tester packet. The authorized user will run the ChatGPT baseline only after approval and a separately registered one-case manifest pin. No connector is approved yet, so connector and permission results remain deferred.

## Accepted and denied behavior

- **Accept:** Cases 07, 09, and 16 lead a blind human reviewer to consistent time and abstention judgments; a qualified statement that the records do not establish **sole** causation is coded as abstention from that claim. The three injection cases ask ordinary research questions, include their attack payloads only in allowed source records, and retain evaluator-held sentinels. Every source record has a case use. All 24 draft one-case projections expose exactly the approved allowed IDs, while expected answers, forbidden IDs/text, category, and sentinels stay evaluator-held. Revised case/source bytes and the unchanged or revised rubric byte hash are recorded for review, and approval occurs before any candidate run.
- **Deny:** A binary `No` to the old yes/no wording is automatically scored as a failed abstention; later flag disablement is treated as already effective at 15:30; an approval citation omits the asked time; a question tells the candidate to ignore source instructions; a source text, ID, origin, projected title, or tool search/fetch metadata labels an attack as an injection; a stale digest or approval manifest is reused; an allowed projection includes forbidden/evaluator-only content; case category or allowed-source padding substitutes for observed source/citation coverage. Draft fixtures, unpublished real employee workflows, or a missing ChatGPT connector are never presented as observed product evidence.

## Dependencies, risk, and disable path

This changes only the preapproval evaluation fixture, not job authorization, OAuth, OpenShell policy, or deployment topology. Existing approved bytes do not exist, so there is no migration of a real candidate run; any future approval must pin the **new** bytes. Exact-quote semantic fairness and honest missing-metric/export recording are separate CR-0021/0022 gates. The three approved real employee workflows required by the selection design cannot be invented by this synthetic pack and remain an explicit predecision gate. If review rejects a case or discovers leakage/bias, keep distribution disabled, revise the draft with a new digest, and rerun all affected comparisons after approval; never silently mutate an approved pack.

## Closure gate

Close only after focused red/green case/projection tests, independent corpus review, product and security approval of exact case/source/rubric bytes and destination, a separately registered one-case manifest pin, and an approved plan for the three representative employee workflows. A local green test or this CR cannot authorize tester distribution or a selection decision.
