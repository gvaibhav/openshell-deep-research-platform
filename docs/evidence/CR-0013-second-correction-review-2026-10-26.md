# Independent second correction re-review: CR-0013 and CR-0009

- **Date:** 2026-10-26
- **Reviewer:** `/root/milestone0_review`, read-only and independent of the build-security implementation
- **Scope:** Malformed Trivy vulnerability/alias fields, direct development-manifest drift, prior eight false-green cases, actual local Trivy/CycloneDX shapes, and local workflow gates
- **Disposition:** No remaining Blocker or Important finding in the scoped local code. [CR-0013](../change-requests/CR-0013-build-security-pipeline.md) remains `In progress`; [CR-0009](../change-requests/CR-0009-design-impact-traceability.md) remains `Open`.

The reviewer reproduced denial of malformed `Vulnerabilities` and `VendorIDs` in `scripts/build_security/gate.py` and of new or incompatible direct requirements absent from `requirements-dev.lock`. The eight cases from the [first correction re-review](CR-0013-correction-re-review-2026-10-26.md) remained denied. On pinned Python 3.13.17, 68 focused build-security tests and the then-current 153-test combined suite passed; lockcheck saw 18 exact development and 60 worker pins. `make check`, Ruff, mypy, and actionlint also passed. This is a code and local-evidence review, not a protected CI run.

The current worker image's [local scan](CR-0013-local-image-scan-2026-10-26.md#current-cancellation-and-full-graph-image-preflight) has 48 high findings. A complete gateway/supervisor/runtime/final-worker digest and platform inventory, approved finding or exception dispositions, runtime OS-class absence proof, signed admission, protected PR checks, daily rescan, and first implementation PR intake remain open. The gate must stay closed for promotion.
