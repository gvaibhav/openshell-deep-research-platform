# CR-0011 blind utility independent correction review, 2026-10-26

**Scope:** Local public/synthetic blind packet preparation, detached witness verification, and unblinding in `eval/blind_review/`. This is not a witnessed candidate run or SEL decision. The independent reviewer used the repository [principal engineer review skill](../../.agents/skills/principal-engineer-review/SKILL.md) and [platform feasibility skill](../../.agents/skills/platform-feasibility/SKILL.md).

## Finding and TDD correction

The first review found a Blocker: a caller-supplied executable such as `/usr/bin/true` could return success for an invalid witness signature. The implementation removed the executable selector and now checks root ownership, non-group/world-writable mode, and exact SHA-256 of `/usr/bin/openssl` before signature verification. The pinned macOS binary is LibreSSL 3.3.6, SHA-256 `49db04c17e3a8c169ebc48a1149d78c165a86c04913203f46b2a14ce7f4a14fc`; another host fails closed pending separate qualification. Preparation and unblinding now call the shared evaluator's full approved-input preflight, and every signed review must score exactly the approved dimensions for its case.

Five focused regressions failed before correction and passed after it: fake success verifier, missing score dimension, extra score dimension, repinned invalid corpus at prepare, and repinned/resigned invalid corpus at unblind. The independent reviewer then reproduced invalid signature, malformed approved case, and signed missing/extra score denials with a genuine synthetic key and receipt. Each denied case left no unblinded file. The final read-only review found **no remaining Blocker or Important code defect within the isolated utility**.

The implementer and reviewer reported 19 focused blind tests and 221 tests across the repository under Python 3.13.17, plus passing `make check`, `make lint`, `make typecheck`, `make lockcheck`, formatting, and `git diff --check`. These are local checks. The repository has no observed candidate scores.

## Open selection proof

The utility accepts a partial packet set; before any observed score counts, the workflow must freeze a complete predeclared candidate×case matrix before label reveal, or use an approved batch protocol that prevents early reveal from influencing later reviews. A scorer binding must re-verify the exact signed packet, map, review, and receipt bytes and match every quality score and candidate/case/run identifier to the labeled result. The v2 run's permission and prompt-injection flags require a **separate, independently corroborated control review**. Raw candidate answer artifacts and screening records must be checked against the packet/map hashes. Human corpus/rubric approval, witness key custody and trusted time, source/tenant event corroboration, matched ChatGPT/restricted/OpenShell runs, and SEL-04 runtime proof are still pending. Withhold unblinding and the SEL decision when any of these required controls is missing.

The [feasibility impact analysis](../feasibility-and-market-assessment.md#matched-evaluation-proof-implementation-impact), [CR-0011](../change-requests/CR-0011-matched-feasibility-evaluation.md), and paired [ToDo](../todos/CR-0011-matched-feasibility-evaluation.md) track the next slice.
