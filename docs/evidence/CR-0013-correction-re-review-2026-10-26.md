# Independent correction re-review: CR-0013 and CR-0009

- **Date:** 2026-10-26
- **Reviewer:** `/root/milestone0_review`, read-only, independent of build-security implementation
- **Scope:** Fail-closed release and PR evidence gates, current local Trivy formats, exact locks, and workflow reachability on Python 3.13.17
- **Disposition:** All eight prior false-green findings are corrected; two new findings leave CR-0013 `In progress`. CR-0009 remains `Open` until protected PR proof.

## Corrected cases independently observed

Temporary-fixture denial probes blocked wrong pip target/ecosystem; missing worker OS inventory; absent, incomplete, or wrong-digest/platform SBOM package sets; truncated KEV catalog; unowned medium findings; worker direct-pin drift; enabled optional GCP host relay; and a tag named `main` falsely treated as a protected branch. Real local Trivy artifacts for the worker and supervisor had matching PURL multisets; the sandbox runtime image has no OS package result and remains correctly blocked pending an independently reviewed digest/platform-specific absence proof.

## New findings

1. **Blocker — malformed vulnerability or alias field can read as empty.** `scripts/build_security/gate.py` uses a falsy fallback for `Vulnerabilities` and `VendorIDs`. In a checksum-updated fixture, `Vulnerabilities: ""` yielded a green release summary; a medium GHSA with `VendorIDs: ""` and ordinary triage also passed, potentially hiding a KEV alias. Accept absent or null only where the observed Trivy format permits it; reject other non-list values. Add release and dependency denial tests.
2. **Important — direct development dependency can be absent from scan.** `make lockcheck` validates the lock but did not read `requirements-dev.txt`, while PR CI installs/scans the lock. Appending a new direct requirement to a temporary manifest left `make lockcheck` exit 0. Compare each direct name and range to the exact resolved lock; add missing and incompatible-version regressions.

## Checks and unrun gates

At review time, 57 build-security tests, full `make test`, lockcheck (18 development and 60 worker pins), Ruff, mypy, actionlint, and `make check` passed on Python 3.13.17. The reviewer inspected local worker and supervisor Trivy JSON/CycloneDX artifacts and did not run a new network-backed image scan. Protected CI, complete final-digest/platform evidence, approved security-owner threshold/exception policy, signed provenance, deployed-inventory proof, and daily rescan remain unrun. The latest worker has 48 high findings and remains development-only. Correction assignment and later disposition are in the [progress report](../progress-report.md) and [CR-0013 ToDo](../todos/CR-0013-build-security-pipeline.md).
