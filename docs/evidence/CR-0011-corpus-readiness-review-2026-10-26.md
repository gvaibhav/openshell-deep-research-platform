# CR-0011 independent draft-corpus readiness review — 2026-10-26

**Reviewer:** `/root/corpus_readiness_review` (read-only). **Scope:** the 24-case synthetic corpus, 29 source snapshots, draft rubric, one-case tester projections, and scorer fairness before product/security approval. **Verdict:** suitable for product/security review as a draft; not ready for approved, scored ChatGPT runs. No candidate was run, no connector was approved, and this review is not an entitlement or live source-permission test.

## Ranked findings

1. **Blocker for scoring — exact expected-quote equality.** `eval/scorecard.py` requires every exact preregistered quote. A full-document `github-deploy-77` citation can support both facts in case-12 yet receive zero because it does not repeat two shorter strings. The scorer needs source-linked span validation with blind human semantic-support review; a valid alternative span and an unsupported span are required allow/deny cases. See the proposed fairness correction under CR-0011 until its own paired impact is linked.
2. **Important — missing observed cost.** The tester guide permits `unknown`, while candidate-run v2 requires numeric `cost_usd` for completed results. The contract must represent unavailable cost with a reason and must never invent zero or discard an otherwise valid completed answer.
3. **Important — report export.** SEL-01 requires report-export evidence, but neither the rubric nor completed-result contract has an explicit export outcome. `answer_artifact_ref` only points to a retained answer.
4. **Important — case wording and behavior.** Case-16's yes/no question permits a correct qualified “No” that can be coded `answer` and incorrectly zeroed against `abstain`; its four exact required citations also magnify the quote problem. Case-09 should distinguish the 15:00 pause from the later 16:00 disablement when asking about 15:30.
5. **Important — coverage realism.** Case-21 cues instruction defense in its question, and all three injection sources label their payloads untrusted. Ten questions reuse two short canary/incident stories. Retain these as sanity cases, add uncued attacks, and obtain the three approved real employee workflows required by the selection design before a build decision. Do not fabricate or distribute employee data before approval.
6. **Optional — fixture clarity.** Case-07's required quote omits the time asked about. `pub-region-old` and `pub-region-new` are unused.

## What the read-only review checked

All 24 one-case projections contained exactly the allowed source IDs and excluded forbidden source text and evaluator-only fields. Every expected quote appeared in its declared allowed source. The canonical source-pack digest matched. These are lexical/fixture checks, not proof of semantic support, tenant isolation, or tool authorization.

| Draft artifact | Raw SHA-256 at review |
| --- | --- |
| `eval/corpus/v1/cases.json` | `0f30e3dafe7d37283d4616b550ec14dcc999134e3aa81b066290903a62344239` |
| `eval/corpus/v1/sources.json` | `b841ac4cc8fff922ba00a0975ec155c7a2d1720415819044edca6f141858a5b4` |
| `eval/corpus/v1/rubric.json` | `7056a9bc9efc922d0bce6e80645d3ca7ce4cab093257af34100e2e281c37846a` |

Canonical source-pack digest at review: `584af17ec77c99d037fceff9dbed01184b1f586a22b2b51194b2de4fe1ea5992`. Draft IDs: `synthetic-matched-research-v1`, `synthetic-research-pack-v1`, `synthetic-matched-rubric-v1`. These digests are historical and must be recomputed after correction; they are not approval pins.

## Human approval and observed-run gates

The product/security approval packet should contain a cover sheet with exact revised digests, data-use destination, thresholds, reviewers, and a 24-row **evaluator-only** matrix of question, allowed/forbidden IDs, behavior/facts, citation anchors, ambiguity, category, and permission or injection sentinels. A tester receives only an independently pinned, approved one-case question and allowed projection. Product/security reviewers sign the exact revised bytes; the manifest digest must be registered separately from the packet generator.

A complete three-arm comparison has 72 candidate×case cells. At an assumed 5–10 minutes per blinded completed answer, quality review alone could require about 6–12 hours, plus separate control review and witness work. This is a planning estimate, not an observation. Human input approval, manifest registration, the user's ChatGPT run, connector/Deep Research tool eligibility, linked-citation parity, real ACL and revocation probes for cases 17–20, representative employee workflows, signed review custody, matched restricted/OpenShell runs, and cost/export observations remain unrun. Deferred cells are not failures.
