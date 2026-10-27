# CR-0011 Linux output publication correction

**Outcome:** Writer-local correction is ready for a draft checkpoint and fresh Linux CI. Independent reviewer `/root/checkpoint_review` found no scoped Blocker or Important finding. Root transcribed this read-only review; it is separate from the CR-0022 review. Requirements: SEL-01/05, RES-09; synthetic evaluator custody only. Intended output-custody design is unchanged under [CR-0011](../change-requests/CR-0011-matched-feasibility-evaluation.md) / [ToDo](../todos/CR-0011-matched-feasibility-evaluation.md).

The real Ubuntu/Python 3.13.17 [run 40457209428](https://github.com/gvaibhav/openshell-deep-research-platform/actions/runs/40457209428), at `6d2600c`, failed two existing output-replacement tests. `_write_new_output` closed the created file descriptor before publication and rollback. Linux could recycle the freed inode, allowing a replacement to match the stored device/inode pair: one test returned success instead of denial, and another deleted a replacement it did not own.

The [writer](../../eval/scorecard.py) now holds that descriptor until publication, final checks, and both internal cleanup paths finish, and closes it in an outer `finally`. This keeps the original inode alive while its identity is used. No signature, authorization, or output-route policy is relaxed.

## Verification

- Root passed both originally failing regressions locally, then all **428** repository tests, check/lint/type/lock gates on Python 3.13.17, focused formatting, actionlint 1.7.12, and diff whitespace checks.
- The independent reviewer passed five existing cases: source replacement denial, preservation of replaced output after failed directory sync, link collision cleanup, valid signed output, and fresh/exclusive output.
- Five additional descriptor-lifecycle probes passed: success, link collision, file-sync failure, directory-sync failure, and unexpected link failure. Every probe closed the temporary descriptor and left no owned temporary file; failure paths left no owned published output.
- Fresh Linux CI is required on the committed correction. This local review is not a protected CI or distribution result.

## Adjacent limitation and disable path

The reviewer identified an **unreproduced, code-derived follow-up** in blind-review map/unblind callers and packet cleanup: some retain returned device/inode tuples after file descriptors close. Same-UID replacement and later inode recycling could undermine subsequent checks or rollback. The Linux writer reproduction supports the mechanism, but the reviewer did not independently reproduce a caller-level scenario and found no cross-UID access. Keep this follow-up under CR-0011 before claiming comprehensive cleanup correctness or enabling distribution: retain handles through caller final checks/rollback and add caller-level replacement regressions.

Keep the PR draft, the evaluator unused for observed selection, and packet distribution closed. The writer-local fix can be reverted independently; that restores the known Linux test failures and must not be described as a qualified fallback.
