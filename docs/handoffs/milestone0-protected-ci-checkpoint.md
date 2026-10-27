# Milestone 0 draft checkpoint and protected CI handoff

This implements the existing intake path for [CR-0009](../change-requests/CR-0009-design-impact-traceability.md) / [ToDo](../todos/CR-0009-design-impact-traceability.md) and [CR-0013](../change-requests/CR-0013-build-security-pipeline.md) / [ToDo](../todos/CR-0013-build-security-pipeline.md), OPS-10/12. Intended design is unchanged. The branch is `codex/milestone0`; the preserved implementation checkpoint is `46ac993`. Only synthetic fixtures, code, and sanitized development evidence belong in this draft. There is no release or packet-distribution approval.

## Local checkpoint evidence

On 2026-10-26, Python 3.13.17 from the existing pinned environment passed `make check`, `make test` (403 tests across five suites), `make lint`, `make typecheck` (23 files), and `make lockcheck` (18 development and 60 worker pins). Actionlint 1.7.12 and `git diff --check` passed. These checks exercise local code and structural contracts, not a protected runner, live tenant, or deployed boundary.

Trivy 0.76.1 rejected the ephemeral synthetic secret canary. An isolated copy of all 276 tracked/nonignored files (3,439,915 bytes) produced zero secret findings, as did the complete patch/commit-message history from `origin/main` to `46ac993` (one commit). The sorted path/content snapshot digest was `55dba28b92a17120aa294e661671a681e25a242330f07751f395d5c3b9f448ed`; later documentation additions require another scan before push. The independent checkpoint reviewer also inspected the current content without exposing credential values. Scanner absence of findings is not proof that every possible secret format is detectable. Ignored local files were not included or published.

## Protected CI path

Read-only GitHub inspection on 2026-10-26 found `main` **unprotected** and no repository rulesets. A green draft-PR run alone therefore does not satisfy protected CI. A repository owner must configure required PR review and these exact status contexts from `.github/workflows/pr-checks.yml`, with current-head enforcement and no ordinary bypass, before executable code merges:

| Required check | Purpose |
|---|---|
| `contracts, lint, types, tests` | Traceability, schemas, deterministic behavior, lint and types |
| `secret scan` | Canary proves scanner rejection, then checkout-content scan |
| `exact lock CVEs and KEV` | Fresh exact development/worker dependency evidence |
| `deployment misconfiguration scan` | Configuration findings, separate from package CVEs |

Retain the draft PR URL, exact head SHA, all four check-run URLs/conclusions, and the applied protection/ruleset evidence. In a disposable PR, demonstrate that a traceability failure and an absent/failed required check block merge, then restore a valid pair and confirm all required checks pass. The PR must cite both CR/ToDo pairs, OPS-10/12, local evidence, and still-open component obligations. Keep CR-0009 Open until that enforcement and first implementation-PR intake are observed. The owner action is documented here; this checkpoint does not change repository settings.

The release-security workflow is a separate gate. Its candidate/deployed manifests remain absent intentionally. Do not create them from example values or enable promotion to get a green badge. The development worker still has 21 retained vendor candidates and 44 HIGH Debian findings; complete image/platform coverage, security-owner policy/dispositions, signed admission, and release proof remain open under CR-0013. No fresh CVE/image scan is claimed by the local checks above.

## Disable and continuation

Keep the PR draft and do not merge while protected enforcement or required evidence is missing. Revert a later isolated slice by its own commit; preserve the checkpoint. CR-0022 may proceed with synthetic red-first tests after this checkpoint, while packet distribution, enterprise data, release promotion, observed selection scoring, and the dashboard/control-plane build remain behind their existing gates.

## Draft PR and first observed runner result

[Draft PR #1](https://github.com/gvaibhav/openshell-deep-research-platform/pull/1) opened at `2c8759c`. The [first PR run](https://github.com/gvaibhav/openshell-deep-research-platform/actions/runs/40456775776) passed secret scan, exact lock CVEs/KEV, and configuration scan. Its quality job failed at `make check` because two historical evidence links were absolute Mac workspace paths. Those links were corrected to repository-relative paths without changing the historical finding. This is real PR-run evidence, but not protected enforcement or final-image/release proof. A later exact-head green run is still required.

A proactive test-portability correction also replaces five Mac-only `/private/tmp` fixture roots with canonical `/tmp`, preserving all denial probes and adding explicit root-owned/sticky assertions to the positive case. All 72 binding tests passed locally; a separate read-only reviewer passed the five affected cases and found no scoped Blocker/Important. This is a green local correction, not a fabricated pre-fix Linux red result. Linux proof requires CI on the corrected commit.
