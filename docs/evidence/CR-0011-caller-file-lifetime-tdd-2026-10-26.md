# CR-0011 caller file-handle lifetime TDD

**Date:** 2026-10-26. **Base:** `a8fcd1b`, branch `codex/milestone0`. **Requirements:** SEL-01, SEL-02, SEL-05, RES-09. **Impact:** DR-FEAS-001. **Data:** synthetic only. **Tracking:** [CR-0011](../change-requests/CR-0011-matched-feasibility-evaluation.md) / [ToDo](../todos/CR-0011-matched-feasibility-evaluation.md). Intended evaluator artifact-custody behavior is unchanged.

This follows the [Linux publication writer correction](CR-0011-linux-publication-fd-review-2026-10-26.md), whose real Linux CI reproduction concerned inode reuse *inside the writer*. That correction retained its descriptor through writer-local checks and cleanup, but returned a device/inode tuple after closing it. Map/unblind callers subsequently used the tuple for final validation or rollback. Packet creation similarly closed each descriptor before later caller cleanup, and closed the descriptor before its own failed-write cleanup. Preparation also lacked a final identity check for each created packet/manifest file.

The implementation subagent `/root/cost_export_scope` owns this slice. Independent reviewer `/root/checkpoint_review` reviews it read-only; the root agent records assignment, return, review disposition, and broader checks in the [progress report](../progress-report.md). Existing modified progress work and root-owned documentation edits were preserved. No git, network, configuration, packet distribution, enterprise source, or release operation was performed by the implementer.

## Implementation and boundary

The [scorecard writer](../../eval/scorecard.py) now returns an explicit `_CreatedFile` owner. Its `identity` is read from the still-open descriptor; using a closed handle fails. `close()` relinquishes ownership once. The writer transfers the descriptor only after successful publication and its existing checks; failures preserve the previous writer-local cleanup-before-close ordering.

The [blind-review utility](../../eval/blind_review/tool.py) retains map and packet/manifest handles through preparation's final validation and rollback, and retains the unblinded file handle through its corresponding final checks and rollback. Every packet and the manifest gets a final regular-file/device/inode check against its held handle. Packet writer failures also clean up while the original inode remains alive. Callers close handles in their final cleanup, after any identity-dependent rollback; the scorer CLI closes its returned handle immediately after the writer completes because it has no further caller file checks.

The existing maximum remains 128 packets, plus one manifest and one map file, so preparation retains at most **130 created-file handles**, in addition to its held directory descriptors. No dependency, artifact schema, signing protocol, approval boundary, output-route policy, or current source permission changes. Private/exclusive output checks and same-directory atomic publication remain in place.

Holding an open file prevents its unlinked inode from being recycled while its identity is used. This does not make name-check-and-unlink atomic against an adversarial process sharing the custodian's UID, prevent same-inode content mutation, or freeze pathnames after return. The operator-controlled OS identity/private-ancestry assumption and separate-OS-custody requirement remain. Exchanged foreign files are preserved for operator reconciliation, not recursively removed.

## Red-first evidence

Commands used `/private/tmp/m0-py31317-venv/bin/python`, **Python 3.13.17**, existing locked dependencies, and synthetic local fixtures. Tests use actual filesystem unlink/recreate operations and inspect real file descriptors. They do **not** forge `stat` metadata, simulate recycled inode numbers, or claim to have observed caller-level inode recycling on this Mac.

Before implementation, six new targeted tests failed:

- `test_preparation_holds_all_artifact_fds_until_final_checks_then_closes`: all created handles were already closed at preparation's final checks.
- `test_map_replacement_after_writer_return_preserves_foreign_file`: map handle was closed immediately after the writer returned.
- `test_packet_replacement_stays_open_through_rollback_and_is_preserved`: packet handle was closed during caller rollback.
- `test_failed_packet_write_holds_descriptor_until_cleanup_then_closes`: packet writer closed its handle before failed-write cleanup.
- `test_unblind_caller_retains_file_until_final_check_and_closes_on_success`: unblind handle was closed at its final check.
- `test_unblind_replacement_after_writer_return_is_denied_and_preserved`: unblind handle was closed immediately after writer return.

The targeted `python -m unittest ... -v` invocation ran **6 tests with 6 failures**, each on the required original-descriptor liveness assertion. A further red test, `test_packet_or_manifest_replacement_cannot_finish_preparation`, ran **1 test with 2 failing subtests**: real packet and manifest unlink/recreate replacements both allowed preparation to return success. This is an observed caller acceptance gap independent of inode reuse. The new final held-file identity checks address both cases.

## Green and verification

- All **7 new tests** pass after the implementation. Replacement paths deny, preserve foreign bytes, remove other owned artifacts on rollback, and close all captured created descriptors on success/error. The packet/manifest test covers both artifact kinds.
- `python -m unittest eval.tests.test_binding eval.blind_review.tests.test_blind_review -q`: **112 tests passed**, including the prior writer replacement/cleanup regressions and signed output success cases.
- Ruff lint and formatting checks passed for the four changed Python files.
- `make typecheck PYTHON=/private/tmp/m0-py31317-venv/bin/python`: **25 source files passed**.
- Focused mypy on all four changed Python files with `--explicit-package-bases --ignore-missing-imports --follow-imports=silent` passed. An exploratory run without `--follow-imports=silent` reported 10 pre-existing annotation errors in imported, unchanged `eval/tests/test_scorecard.py`; that file is outside the established Makefile typecheck set and was not edited.
- `git diff --check` passed.

Independent review, full root-run gates, and CI on the eventual committed diff are recorded separately. These local checks establish descriptor lifetime and the tested identity/cleanup behavior; they do not establish external witness independence, actual source events, observed selection, or distribution approval.

## Remaining gates and disable path

Keep CR-0011 **In progress**. Approved inputs and original-run truth, reviewer/control/witness custody, the CR-0021/0022/0025 integration and observation gates, packet distribution, enterprise data, release promotion, and the full dashboard build remain closed as documented.

Revert this caller-lifetime slice independently while preserving the earlier writer-local correction if rollback is required. Such rollback restores the known caller lifetime/final-validation gaps, so observed scoring and packet distribution must remain disabled; rollback is not a qualified fallback. No live service or released artifact is affected by this repository-only change.
