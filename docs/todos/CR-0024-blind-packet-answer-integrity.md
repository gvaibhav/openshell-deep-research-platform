# ToDo for CR-0024: Bind the blind packet answer to the candidate answer

- **ID:** CR-0024
- **Status:** In progress
- **Impact ID:** DR-FEAS-007
- **Phase:** Milestone 0, before any observed packet distribution or scoring
- **Accountable team:** Research evaluation and evaluator custody (proposed)
- **Component paths:** `eval/blind_review/tool.py`, `eval/binding.py`, `eval/schemas/`, `eval/blind_review/tests/`, `eval/tests/`, `eval/blind_review/README.md`, `eval/README.md`
- **Requirement IDs:** SEL-01, SEL-05, RES-09
- **Change request:** [CR-0024](../change-requests/CR-0024-blind-packet-answer-integrity.md)
- **Primary design:** [v3 matched-evaluation contract](../design/matched-evaluation-contract-v3.md)
- **Detailed impact analysis:** [Matched-evaluation packet integrity impact](../feasibility-and-market-assessment.md#matched-evaluation-packet-answer-integrity-impact)

## Tasks and proof

- [x] Write a red completed-cell fixture with a wrong `raw_answer` and a repaired `packet_answer`, including valid screening hashes. `prepare` rejects it without distributing a packet.
- [x] Write a second red fixture whose map, raw observation, packet, blind review, control review, and receipt are consistently re-signed around different raw/packet answers. `unblind` and scorecard binding reject it, with no labeled output or ready scorecard. Include an unchanged-answer allow case.
- [x] Enforce exact UTF-8 equality in preparation and independent signed-bundle verification. Verify the signed packet answer and raw-answer hash against the exact retained observation; do not normalize or substitute redacted prose. Keep the control review's independent raw-run corroboration obligation.
- [x] Update the current blind custody/evaluation guides and affected CR-0011 handoff. Document identity-leak quarantine, noncompleted evidence, unauthorized-source violation handling, and old signed-bundle rejection.
- [x] Run focused blind/binding tests, full `make test`, `make check`, Ruff lint/type/format, and an independent principal-engineer/evaluation review on pinned synthetic inputs. Record red/green output, reviewer disposition, and any unrun external raw-run or witness-custody gate.
- [ ] Link the implementation pull request and its protected CI result to the reviewed code/test hashes; reconcile the as-built pair before marking it Verified. No implementation PR or protected result is recorded yet.

## Evidence and closure

The [design review](../evidence/CR-0021-0022-v3-design-independent-review-2026-10-26.md) is the intake finding. Four red-first prepare/signed-verification cases passed; the current evaluator suite passes **167** focused tests on Python 3.13.17. Full `make test`, `make check`, lint, typecheck, lockcheck, scoped Ruff format, and diff checks passed locally. [Independent code review](../evidence/CR-0011-0024-final-custody-independent-review-2026-10-26.md) rechecked a fully re-signed answer mismatch at unblinding and scorer binding and found no remaining scoped Blocker/Important. This pair remains **In progress** until the implementation PR/protected CI result is recorded and matched to the independently reviewed code. External original-run truth, witness custody, packet distribution, and observed-run proof remain under open CR-0011/0021/0025; withhold unblinding for selection, scorecard readiness, and SEL use until those gates pass.
