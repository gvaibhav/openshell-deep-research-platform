# CR-0018: Local tunnel-client MCP conformance probe

- **Date and scope:** 2026-10-26; disposable synthetic `case-17` fixture through the vendor's `tunnel-client dev proxy` in-memory control plane and in-process tunnel client. The only ingress was a temporary loopback URL. A fake API-key string and synthetic tunnel IDs were used; no hosted tunnel, ChatGPT tenant, real credential, enterprise source, or OpenShell gateway was contacted.
- **Pinned client:** Official OpenAI `tunnel-client` v0.0.18, commit `274a5588414819f063d27100a4fb1096aae3830f`. Release ZIP SHA-256 `ba7a0994f7dd15bc8708aa1602ecf54371a492319a641ab9c33dc00f1fd56bfe`; extracted binary SHA-256 `5a55fd3dde505b2ee27f970dad18e6c08e04ffb9d7bc4256c507b8f312c1d6e8`. The [vulnerability preflight](CR-0018-tunnel-client-vulnerability-preflight-2026-10-26.md) still blocks credential-bearing use without a patched artifact or security-owner disposition.
- **Fixture binding:** Projection `case-17` SHA-256 `40ab49779052a0aa1159469fccf7eddf5780215ed24d6988be3f0d8ce1a14559`. The local shim-enabled profile SHA-256 was `05f3648ae2d536a0b0e2e0738dbe8646b033ad69e07ca0eb81bd2617df76c2fe` and explicitly set its base URL to loopback. The shim-disabled profile SHA-256 was `7053b5e0609ff64d5ab28afee31ee233ae286a4fcc54d9a3bef8484519f15899`; it retained the sample hosted URL, which `dev proxy` overrides with its in-memory Unix-socket control plane. The probe did not use that hosted URL.

## Observed allow and deny

| Probe through local proxy | Observation |
| --- | --- |
| `initialize`, MCP `2025-11-25`, shim enabled | HTTP 200 and fixture server's `protocolVersion: 2025-11-25` |
| `tools/list` | HTTP 200; exactly `search` and `fetch` |
| `fetch(id="acl-a")` | HTTP 200; structured result ID `acl-a`, `isError: false` |
| `fetch(id="acl-b")` | HTTP 200; no source result, `isError: true` |
| Unknown `write` tool | HTTP 200 JSON-RPC response with error code `-32602`; no write tool advertised |
| Shim disabled: `initialize` then `tools/list` | Initialize returned HTTP 200, but `tools/list` returned HTTP 409. This reproduces the need for the initialized-notification shim with a caller that omits that notification. |

The shim-enabled proxy log SHA-256 was `2e30f1f43ba6ac23e033b9a396603b92ced9b351e61672baebaab01acf0859fa`; the shim-disabled log SHA-256 was `4fd4ad0da399a3ce40ef9ddba4e66162d753ee8a46fa49a8369b8e119bd5061e`. These temporary logs and profiles are outside the repository and contain only synthetic target metadata. Both proxy processes exited after the probes, and no listener remained on their observed loopback port.

This proves a **local** v0.0.18 legacy MCP path and its shim setting for this fixture. It does not prove hosted Secure MCP Tunnel connectivity, the client's modern `server/discover` fallback in a ChatGPT call, custom-app tool discovery, Deep Research source eligibility, user OAuth or source ACLs, linked citation parity, or a matched candidate run. Those remain open in [CR-0018](../change-requests/CR-0018-chatgpt-synthetic-mcp-baseline.md) / [ToDo](../todos/CR-0018-chatgpt-synthetic-mcp-baseline.md).
