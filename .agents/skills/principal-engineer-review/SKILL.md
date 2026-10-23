---
name: principal-engineer-review
description: Independently review material design, code, or release changes to this research platform for correctness, operational impact, justified complexity, and security.
---

# Principal engineer review

Use after a material cross-component change, a change to an identity/source/sandbox/result boundary, or before a release candidate. An ordinary small documentation or presentation edit can use normal pull-request review. A required independent review must come from someone other than the implementer; self-review is preparation and leaves that gate unrun. **Review read-only:** inspect and report; leave fixes to an implementation task and request an independent re-review afterward.

## Establish the review scope

- Get the intended outcome, requirement IDs, change base and full diff (including new files), data class, affected trust boundaries, pinned versions, contract and policy changes, positive/negative test evidence, unrun gates, and rollback path. Start with `git status` so existing work is not mistaken for the proposed change.
- Read the affected [requirements](../../../docs/requirements.md), [architecture](../../../docs/architecture.md), designs, and [contracts](../../../contracts/README.md). Inspect relevant code when it exists. For a platform decision, revisit the [matched incumbent comparison](../../../docs/feasibility-and-market-assessment.md).

## Evaluate the change

- **Fit and simplicity:** Does it satisfy the named requirements and failure cases with a supportable amount of code and operational machinery? Check API/schema compatibility, migration, retry, cancellation, audit, cost limits, and rollback where affected.
- **People using and operating it:** Can a researcher understand the acting source identity, result visibility, denial, and partial failure? Can an operator identify a failed issuer, broker call, sandbox admission, CVE gate, or cleanup attempt without exposing secrets?
- **Trust boundaries:** Trace untrusted browser, source, MCP, and model data to each privileged operation. Check tenant and exact Okta-group job access; current source rights on private reports and evidence; OAuth issuer/resource/audience and token custody; broker tool-argument and response limits; full-graph placement inside OpenShell; effective policy, provider receipt, CNI enforcement, and public/private lane separation as applicable. Review evidence integrity and retained-artifact access.
- **Proof:** Compare claims with actual contract tests, research evaluations, CVE/SBOM results, and live Okta/MCP/OpenShell/network observations. Map a precise code weakness to a CWE when useful; do not force a CWE label onto a design tradeoff. The [promotion gates](../../../docs/design/deployment-and-operations.md#10-promotion-integration-gates) determine which live checks are required.

## Return a review, not a patch

- Lead with actionable findings ordered as **Blocker** (credible unauthorized access, data loss, or required behavior broken), **Important** (material correctness, reliability, or operability gap), then **Optional** (small simplification or clarity improvement). For each finding give `path:line`, the failure scenario, affected requirement or boundary, and a concrete fix or missing proof. Omit empty severity groups and avoid style-only comments.
- List **unrun required gates** separately from defects. In this design-only repository, an absent live sandbox, OAuth, or CVE result is an unrun future promotion gate; do not call it passed or automatically treat it as a flaw in a design document. State what this review can support now and whether the reviewed artifact is ready for its **next stage**. A review never substitutes for CI, source/IdP/security-owner decisions, or production sign-off.

Adapted for this project from NVIDIA OpenShell's [principal engineer reviewer profile](https://github.com/NVIDIA/OpenShell/blob/main/.opencode/agents/principal-engineer-reviewer.md). That upstream file is an OpenCode subagent profile; this file is a portable repository skill.
