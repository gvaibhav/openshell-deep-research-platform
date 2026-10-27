# CR-0018: independent local fixture re-review

- **Date:** 2026-10-26
- **Reviewer:** Separate read-only principal-engineer/feasibility agent `/root/milestone0_review`
- **Scope:** Synthetic/public `eval/mcp_fixture/` implementation and runbook, `Makefile` test/typecheck reachability, and the earlier four Important findings plus a newly reproduced malformed-Unicode crash. No real tunnel, key, tenant, or enterprise source was used.
- **Disposition:** No remaining local Blocker or Important finding after TDD correction. [CR-0018](../change-requests/CR-0018-chatgpt-synthetic-mcp-baseline.md) and its [ToDo](../todos/CR-0018-chatgpt-synthetic-mcp-baseline.md) remain `In progress` for external conformance and matched-run proof.

## Independently observed checks

The reviewer inspected the runbook's tunnel-client v0.0.18 `mcp.stdio_send_initialized_notification` setting for both `doctor` and `run`, fresh conversation per case, selected app/source-state capture, and raw tool transcript requirement. The projector and server share the exact source-ID grammar, 64 KiB encoded projection bound, and 32 KiB worst-case search/fetch response bound. `make test` includes the fixture suite and `make typecheck` covers its source and tests.

The reviewer reproduced the new crash before correction: a JSON-escaped lone-surrogate request ID terminated the stdio process before a subsequent valid ping. After correction, the same process returned generic JSON-RPC `-32600` with a null ID, answered the valid ping, and exited 0. A recomputed-hash projection containing a lone surrogate exited 2 without a traceback. Valid escaped emoji-pair IDs remained accepted in the regression tests.

All **24** draft case projections were independently checked for exact allowed IDs, absence of evaluator-only fields and forbidden source ID/text, and valid server loading. A selected-case `acl-a` fetch succeeded. Forbidden `acl-b`, other-case, and unknown IDs received identical denials; a write tool was rejected. Malformed initialization did not permit tool use before a proper notification.

On Python 3.13.17 the reviewer ran 19 focused fixture tests, `make test`, `make lint`, `make typecheck`, `make check`, `make lockcheck`, and `git diff HEAD --check`; all passed. These are local code/structure checks and do not prove a live tunnel or source ACL.

## Still open

Pinned MCP Inspector and actual tunnel-client handshake, ChatGPT custom-app discovery and Deep Research eligibility, fresh-conversation selected-source/tool transcript, usable citation-link parity, approved matched candidate runs, protected CI, and a reviewed exact tunnel-client CVE disposition are unrun. The inspected v0.0.18 binary's [high finding](CR-0018-tunnel-client-vulnerability-preflight-2026-10-26.md) prevents credential-bearing use until a patched artifact or security-owner disposition and current rescan are recorded. Blank fixture URLs cannot count as linked ChatGPT citations. Local one-case scoping does not prove per-user source authorization.
