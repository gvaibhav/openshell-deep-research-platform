# CR-0013 and CR-0009: independent build-security review

- **Date:** 2026-10-26
- **Reviewer:** `/root/milestone0_review`, read-only principal-engineer sub-agent.
- **Scope:** Draft PR/release workflows, `scripts/build_security/`, locks, Makefile, local scanner evidence, [CR-0013](../change-requests/CR-0013-build-security-pipeline.md) and [CR-0009](../change-requests/CR-0009-design-impact-traceability.md).
- **Result:** Four reproduced fail-closed Blockers and four Important gaps. Promotion and both component CRs remain open.

| Severity | Reproduced finding | Required correction |
|---|---|---|
| Blocker | `gate.py` accepted an `os-pkgs`/Alpine report with `Target=not-the-lock` and matching package names as proof of the Python dependency lock. | Require the observed pip ecosystem result for the isolated copied `requirements.txt`, exact target, and all locked package/version rows. |
| Blocker | The worker release gate passed after the Debian OS package result was removed, because a claim of `os` plus `library` scanning and any nonempty package result sufficed. | Validate the required actual OS and language package classes per image; independently justify a genuinely absent class. |
| Blocker | An SBOM containing only busybox while the scan contained Python packages passed. A wrong OCI PURL digest also passed after the adjacent checksum was updated. | Match exact digest and deployed architecture in the SBOM root/PURL and reconcile its package inventory with the scan and worker lock. |
| Blocker | A truncated KEV feed declared `count: 1756` but contained one entry; a medium KEV finding then passed. | Validate count, entries, and unique CVE IDs before applying KEV policy. |
| Important | A medium/low finding could produce a green summary with no owner or due date. | Retain an owner and due date or block promotion under the project policy. |
| Important | Direct worker pins and the version manifest can drift from the hash lock while release validation stays green. | Compare the direct pins and manifest to the resolved lock with a drift regression. |
| Important | Optional `requirements-relay-gcp.txt` does not have a separately resolved host-relay lock/scan, even though `google-auth` also appears transitively in the worker lock. | Lock and scan the actual host relay environment if this optional GCP path is enabled; otherwise keep it disabled. |
| Important | Release workflow compares only `GITHUB_REF_NAME` with default branch; a simulated `refs/tags/main` passes. | Compare full `GITHUB_REF=refs/heads/<default>` and retain external protected-branch proof. |

The reviewer ran the 34 build-security tests, `make lockcheck` (11 development and 60 worker pins), Ruff/mypy, actionlint 1.7.12, a synthetic secret canary and local secret/configuration scan, and `make check`; these passed. The reviewer inspected prior local Trivy outputs but did not rerun network-backed scans. Local Python 3.13.11 differs from the workflow's pinned 3.13.17, so a pinned CI result remains unobserved. Full final digest/deployed-platform scans, complete SBOMs, release manifest, security-owner finding policy, protected CI, signed provenance/admission, deployed-inventory reconciliation, and daily rescan are still pending.

**Disposition:** Root assigned TDD corrections to the original build-security implementer. Re-review after red/green cases and actual scanner evidence are available. A local validator does not qualify a release.
