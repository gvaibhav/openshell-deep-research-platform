# CR-0023 neutral metadata final independent review — 2026-10-26

**Verdict:** No remaining Blocker, Important, or Optional finding in the scoped local corpus and MCP fixture correction. The previous [tester-visible injection cue](CR-0023-corpus-correction-independent-review-2026-10-26.md) is absent from the revised exact bytes. The draft is ready for product and security **approval review**. It remains `pending` and cannot be distributed or scored until the separate human, manifest, connector, and evaluation gates below pass.

**Scope:** Independent read-only re-review of [CR-0023](../change-requests/CR-0023-corpus-fairness-and-coverage.md) / [ToDo](../todos/CR-0023-corpus-fairness-and-coverage.md), DR-FEAS-006, SEL-01/02/05 and RES-09. Data class: wholly synthetic. Trust boundary: evaluator-held case setup, expected facts, citation anchors, forbidden records, permission targets, and injection sentinels versus the one-case question and allowed source view delivered to a tester. The repository's platform-feasibility, research-worker-evaluation, and principal-engineer-review skills guided this review. Only this evidence file was written; code and fixtures were not edited by the reviewer.

## Exact draft identity

The IDs remain `synthetic-matched-research-v1`, `synthetic-research-pack-v1`, and `synthetic-matched-rubric-v1`; both corpus and rubric say `approval.status: pending`. Independent raw-byte and sorted compact UTF-8 canonical JSON SHA-256 calculations match the [evaluator-only approval cover](../../eval/corpus/v1/approval-review-draft.md) and [CR-0023 ToDo](../todos/CR-0023-corpus-fairness-and-coverage.md).

| Input | Raw SHA-256 | Canonical JSON SHA-256 |
| --- | --- | --- |
| `cases.json` | `ce3412990a8f9daa24ce682b170b2cbc792130a424ce93b69d7725c578f7d615` | `4fc792634652768cc17f99fd3c267c744f0a0ffef9ee154e49dcfa6111517329` |
| `sources.json` | `ecba311adb883bda74bec5e98998246f03be6463bfc3e4960a55add8239945f6` | `e3130662184387d0211a427b4213c4de24f8734016933de90cd5a3aa7586513d` |
| `rubric.json` | `7056a9bc9efc922d0bce6e80645d3ca7ce4cab093257af34100e2e281c37846a` | `fee02c9e21c52aa277f18bcd0714104d1bc59020bbc25af0730da8db05d78f79` |

The corpus-declared source-pack digest is `e3130662184387d0211a427b4213c4de24f8734016933de90cd5a3aa7586513d` and matches the canonical source pack. For instruction-parity qualification, current raw file SHA-256 values are `server.py` `5aef93d45c79fce6511a47c3067c4bd558eea92872e81980da09682aa8a7acfe` and spike `worker.py` `339e6dca5fec77151fee5d8e88d7fe4255faf20ee24c5776cf9126d8cbc35717`; these are **source-file**, not effective per-run prompt, hashes.

## Findings

No remaining Blocker, Important, or Optional finding was identified in the changed corpus values, neutral source metadata, projector, or local MCP response boundary. This conclusion is limited to the pinned draft and the local deterministic checks below. It does not assess research quality or source authorization in the ChatGPT tenant.

## Independent checks

- Parsed exactly 24 unique cases (`case-01` through `case-24`) and 29 unique synthetic source snapshots. Every source is used as allowed evidence or an explicit denial target; category counts match the rubric. Every expected quote occurs in its referenced allowed source, and source families match the declared public, Slack/GitHub, GCP Logging/GitHub, ACL, or prompt-injection case. These are lexical and category checks, not human semantic citation judgments.
- Built and server-validated all 24 draft one-case projections. Each contains exactly its case's allowed source IDs, no forbidden source ID or text, and no evaluator-only category, setup, behavior, facts, citation anchors, permission target, rubric dimensions, or sentinel fields. [Case 07](../../eval/corpus/v1/cases.json) still anchors the asked approval time; case 09 separates the 15:00 pause from the later 16:00 flag disablement; case 16 explicitly codes a qualified refusal to claim sole causation as abstention with two evidence anchors.
- Independently ran the actual in-process MCP `initialize` → `notifications/initialized` → `search` → `fetch` sequence for each of cases 21–23 under legacy MCP `2025-11-25`. Inspected every returned source `id`, `title`, `url`, `text`, `metadata.origin`, and `metadata.data_class`, plus both `structuredContent` and its identical JSON text content. Search/fetch returned only the selected case's single allowed source: `pub-metrics-note` / `synthetic-public-page:metrics-note`, `github-package-readme` / `synthetic-github:package-readme`, and `gcp-event-count` / `synthetic-gcp-logging:event-count`. No old `inj-`, `with-injection`, evaluator field, forbidden ID, or attack-category label appeared in those source IDs, titles, origins, search results, or fetch metadata. The lower-trust source **text** still contained each case's evaluator-held attack sentinel and the substantive malicious instruction; the question did not announce an injection test. The source text's attack instruction is the test input, not a protective category label.
- A modified source pack was refused because its canonical digest no longer matched the corpus. The previous raw source-pack pin was refused against the revised source bytes; a wrong projection SHA-256 was refused by the MCP server; pending corpus/rubric inputs could not produce a manifest candidate. These tests establish local stale-pin denial, not independent approval-register custody.
- [The focused regression](../../eval/tests/test_corpus_readiness.py) now checks the whole projection and actual MCP search/fetch outputs for case 21–23 metadata cues. The [approval outline](../../eval/corpus/v1/approval-review-draft.md) and [fixture guide](../../eval/mcp_fixture/README.md#instruction-parity-for-injection-cases) explicitly keep evaluator material out of the tester packet and record the generic instruction-parity caveat.

## Local command results

Checks used `/private/tmp/m0-py31317-venv/bin/python` (Python 3.13.17). These are local, not protected CI or live tenant tests.

| Check | Observed result |
| --- | --- |
| Independent Python count/hash/24-projection/in-process MCP/stale-pin scripts | Passed. |
| `python -m unittest eval.tests.test_corpus_readiness -q` | 7 passed. |
| `python -m unittest discover -s eval/mcp_fixture/tests -q` | 35 passed. |
| `PYTHON=<3.13.17 tool venv> make test` | Passed across all Makefile test suites; no candidate run occurred. |
| `PYTHON=<3.13.17 tool venv> make lint`; `make typecheck` | Passed; mypy reported no issues in 19 source files. |
| `python -m ruff format --check eval/tests/test_corpus_readiness.py`; `git diff --check` | Passed; Git diff check does not cover untracked files. |
| `PYTHON=<3.13.17 tool venv> make check` | Passed after this review file was added: 25 JSON Schemas, 21 examples, 11 OpenAPI operations, 122 Markdown files, 107 Mermaid fences, and 23 CR/ToDo pairs. Structural only. |

## Unrun gates and disable path

The MCP `initialize.instructions` response still gives generic guidance to treat source text as untrusted; the restricted/OpenShell worker's retrieval prompt gives analogous guidance at [worker.py line 141](../../spikes/full_graph/spike/worker.py). The exact effective model prompt and how ChatGPT receives tool instructions have not been observed. The [evaluator outline](../../eval/corpus/v1/approval-review-draft.md#instruction-parity-to-inspect-in-injection-cases) and [fixture guide](../../eval/mcp_fixture/README.md#instruction-parity-for-injection-cases) require per-run instruction bytes/hashes, source-delivery and tool-result capture, and a qualified or deferred injection comparison if delivery differs. This is an **unrun matched-evaluation gate**, not a remaining local corpus defect.

Product/security approval of the exact case/source/rubric bytes, thresholds, and ChatGPT Enterprise data-use destination; an independently registered final one-case manifest pin; an approved connector and observed Deep Research eligibility; matched ChatGPT/restricted/OpenShell runs; independent signed blind/control evidence; and the [three approved real employee workflows](../feasibility-and-market-assessment.md#5-matched-pilot-and-decision-gates) remain absent. A file upload or no-auth synthetic fixture cannot prove cases 17–20 source permission and revocation behavior. Citation fairness [CR-0021](../change-requests/CR-0021-citation-support-fairness.md) and honest unknown-cost/report-export recording [CR-0022](../change-requests/CR-0022-observed-cost-and-report-export.md) are separate pre-scoring dependencies. Local checks do not qualify OpenShell/CNI, tenant OAuth, or a production release.

Keep tester distribution, any tunnel carrying this draft, and SEL scoring disabled while approval and manifest pins are absent. If a reviewer rejects a case or a later projection/citation parity check finds drift, withhold the packet, version and reapprove the changed bytes, and rerun affected candidate arms; if a tunnel has subsequently been enabled, stop it and revoke its runtime key while the approved source view is corrected. No selected feature or live connector is enabled by this review.
