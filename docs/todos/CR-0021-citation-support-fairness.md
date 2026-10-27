# ToDo for CR-0021: Accept semantically supported alternative citation spans

- **ID:** CR-0021
- **Status:** In progress
- **Impact ID:** DR-FEAS-004
- **Phase:** Milestone 0, before human corpus approval or observed scoring
- **Accountable team:** Research evaluation and product owner (proposed)
- **Component paths:** `eval/target_projection.py`, `eval/scorecard.py`, `eval/blind_review/`, `eval/schemas/`, `eval/tests/`, `Makefile`, `eval/README.md`, `docs/feasibility-and-market-assessment.md`
- **Requirement IDs:** SEL-01, SEL-05, RES-09
- **Change request:** [CR-0021](../change-requests/CR-0021-citation-support-fairness.md)
- **Primary design:** [Milestone 0 implementation intake](../design/implementation-plan.md#6-milestone-0-implementation-intake)
- **Detailed impact analysis:** [Matched-pilot fairness impact](../feasibility-and-market-assessment.md#matched-evaluation-fairness-and-observation-impact)
- **Proposed component design:** [v3 matched-evaluation observation contract](../design/matched-evaluation-contract-v3.md)

## Tasks and proof

- [x] Implement an **isolated** deterministic target-projection module/schema on synthetic approval doubles, with raw-pin/canonical-manifest checks, strict allowlist, 128-target/128-KiB bounds, and 16 red-first-to-green focused tests. Add module/tests to `make typecheck`. This helper remains unused and its `preverified_*` inputs do not verify the required CR-0025 preliminary signature.
- [ ] Derive only from independently pinned raw corpus/source approval bytes and the FD-held packet **after** the CR-0025 preliminary control signature over exact manifest/packet IDs and hashes is verified; require canonical digest agreement with that pre-attested manifest. Enforce at most 128 targets and 128 KiB of encoded projection bytes without truncation; deny a stale, unapproved, or oversized derivation. Keep this isolated helper non-authoritative until signature and witness integration.
- [ ] Feed one immutable verified FD-read packet byte buffer to both target derivation and blind reviewer delivery. Before display, hash the exact bytes the reviewer edge received and compare raw SHA-256 and packet ID with the preliminary attestation; retain the delivered digest. Red-first deny a post-verification/pre-delivery path switch to packet B and a label-bearing B even when packet A and its target projection were valid. No pathname reopen or reserialization after verification.
- [ ] Freeze a deterministic reviewer-only target-projection schema/derivation from approved corpus/source/packet bytes; v2 review entries with per-entry domain-separated signatures; independently pinned reviewer-key register; support findings; labeled candidate-run assembly; and scorecard representation before observed runs. Deny leaked/stale/extra projection fields and migrate or reject older signed artifacts explicitly.
- [ ] Write the **red** case-12 full-document accepted-citation test; retain the unrelated same-source zero-score fixture as a regression guard. Add absent/forbidden source, missing/duplicate target, wrong projection digest, custodian-forged reviewer ID/finding before witness freeze, malformed/duplicate/unpinned/expired reviewer key or registry, signer-role reuse, and changed signed-finding denials.
- [ ] Implement source-exact quote validation and per-target semantic support decisions without requiring equality to preregistered anchor text. Keep expected source-family, allowed/forbidden ID, permission, and injection gates.
- [ ] Require [CR-0025](../change-requests/CR-0025-candidate-citation-provenance.md) / [ToDo](CR-0025-candidate-citation-provenance.md) to bind candidate-native citations before a signed support finding can count; source-exact packet text alone is insufficient.
- [ ] Update approval pack, examples, changed schemas, scorer/binding code, and evaluation guide in the same change. Keep the packet and path-catalog v2 shapes only with strict referenced-version verification; never show expected anchors or reviewer target projections to the candidate/tester.
- [ ] Verify reviewer signatures before control/witness freeze **and** at scorer binding using an externally pinned key register; bind register digest and signed review bytes in witness v4. Run focused tests, `make check`, lint/type/format, and independent principal-engineer/evaluation review on pinned inputs. Record code review, delivery/independence limits, and actual observed-run limits.
- [ ] Obtain human product/security approval of the revised corpus/rubric before distribution. Do not claim actual semantic support from synthetic unit tests alone.

## Evidence and closure

The [read-only corpus review](../evidence/CR-0011-corpus-readiness-review-2026-10-26.md) is the intake finding. The [independent v3 design review](../evidence/CR-0021-0022-v3-design-independent-review-2026-10-26.md) requires the reviewer-only projection and version handoff above. Isolated [projection code](../../eval/target_projection.py), [schema](../../eval/schemas/reviewer-target-projection.schema.json), and [tests](../../eval/tests/test_target_projection.py) now pass 16 focused tests and local full test/check/lint/type/lock gates on draft synthetic input. The [independent isolated-helper review](../evidence/CR-0021-target-projection-independent-review-2026-10-26.md) found no scoped Blocker/Important and independently probed five denials; it did not review a distributor or signer integration. An implementation PR, preliminary-signature integration, signed reviewer findings, approved corpus digest, and observed candidate results remain pending. This pair remains **In progress**. Disable by withholding packet distribution, signed scoring, and the SEL decision.
