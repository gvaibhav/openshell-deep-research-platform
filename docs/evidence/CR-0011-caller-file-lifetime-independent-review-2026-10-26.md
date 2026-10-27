# CR-0011 caller file-lifetime independent review

**Date:** 2026-10-26. **Reviewer:** `/root/checkpoint_review`, read-only and separate from implementer `/root/cost_export_scope`; root transcribed the return. **Scope:** complete `a8fcd1b` to working-tree follow-up, including new tests, [TDD evidence](CR-0011-caller-file-lifetime-tdd-2026-10-26.md), and affected documentation. **Requirements:** SEL-01, SEL-02, SEL-05, RES-09; DR-FEAS-001. **Data:** synthetic only. **Tracking:** [CR-0011](../change-requests/CR-0011-matched-feasibility-evaluation.md) / [ToDo](../todos/CR-0011-matched-feasibility-evaluation.md).

The reviewer used the [principal engineer review skill](../../.agents/skills/principal-engineer-review/SKILL.md) and reported **no scoped Blocker or Important finding**. The correction is ready for the draft checkpoint and fresh Linux CI. This review does not close CR-0011 or approve distribution or selection.

## Reviewed behavior

Explicit `_CreatedFile` handles keep map, unblind, packet, and manifest identities alive through caller final validation and rollback. Packet/manifest final identity checks close the reproduced replacement-acceptance gap. Callers close handles after identity-dependent cleanup. The prior writer-local correction remains intact.

The review distinguishes real unlink/recreate substitutions and observed descriptor lifetimes from caller-level inode recycling, which was not observed on this Mac. Retained file handles do not make pathname check/unlink atomic against a hostile same-UID process, prevent mutation within an inode, or guarantee custody after return. Those limitations remain documented.

## Independent checks

Python **3.13.17**, using the existing locked environment:

- **112 binding/blind-review tests passed**, including all seven new regressions and prior writer-local replacement cases.
- Descriptor exhaustion at map creation: both retained packet/manifest descriptors were live at the failure, owned artifacts were removed, and the handles closed.
- Packet `fsync` failure after a real unlink/recreate: foreign replacement bytes survived and the created handle closed.
- Late unblind caller validation failure: the owned output was removed and its handle closed.
- `git diff --check` passed. The reviewer found no plausible credential or content leak in the diff.

Reviewed Python file SHA-256 values:

| File | SHA-256 |
|---|---|
| [scorecard.py](../../eval/scorecard.py) | `f4d29a875f451dc39b2b549d0f1384307ae910176d351019b9ce3f3c99aaf6ea` |
| [blind-review tool](../../eval/blind_review/tool.py) | `9008abd398de64b2b2f995e769c9f0195dccfc881abc6ea9ae4c56c124a959a0` |
| [binding tests](../../eval/tests/test_binding.py) | `371906cd410df7556acbdef82400a4c8c12c8dbc69321a82a77ce07095a1d8f1` |
| [blind-review tests](../../eval/blind_review/tests/test_blind_review.py) | `3e0432dd18376357bf96ed17e32aef104f7b87d8d26c984dff69be6a6d74a109` |

Root separately passed all **435 tests**, repository validation, lint, the established 25-file typecheck, both dependency-lock checks, changed-file formatting, actionlint 1.7.12, and diff checks. Trivy 0.76.1 rejected a synthetic canary; candidate content and full PR history/pending patch scans returned zero secret findings. Root records final committed CI results in the [progress report](../progress-report.md) and [draft PR #1](https://github.com/gvaibhav/openshell-deep-research-platform/pull/1).

## Unrun gates and disable path

At review return, Linux CI on the committed follow-up was pending. Protected merge enforcement, approved corpus/rubric and observed runs, original-run/source truth, independent reviewer/control/witness custody, CR-0021/0022/0025 signed integration, and the human SEL decision remain open. Packet distribution, enterprise data, release promotion, and the full dashboard build remain gated.

Revert only this follow-up if required, preserving the earlier writer correction. That restores the known caller gaps and is not a qualified fallback; keep observed scoring and distribution disabled. No live service or release was changed.
