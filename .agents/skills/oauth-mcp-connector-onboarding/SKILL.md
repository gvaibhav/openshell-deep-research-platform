---
name: oauth-mcp-connector-onboarding
description: Design and implement one approved read-only OAuth or MCP source connector with broker-side authorization and grant conformance tests.
---

# OAuth MCP connector onboarding

Use for one new or changed Slack, GitHub, GCP Logs, or other protected source. Read the [identity matrix](../../../docs/design/identity-and-access.md), [broker design](../../../docs/design/mcp-connector-broker.md), and [connector requirements](../../../docs/requirements.md#54-connectors-mcp-and-source-grants).

- Obtain the source owner's approved identity model: delegated user or application, exact issuer, OAuth resource/audience, scopes, grant type, refresh/revocation, MCP transport/revision, resource selectors, read tools, and data class. Test client credentials only when that issuer and server support it.
- Keep source grants and refresh material in the broker or its secret boundary. The worker receives a short-lived job identity; never pass a dashboard, gateway, or unrelated MCP token through as the source token.
- Bind every broker call to the server-held tenant, job, source, tool, selector, time range, and byte/rate limit. Reject an allowed tool with out-of-scope arguments, and bound/classify the response. Source text and MCP tool descriptions cannot change the policy.
- Start with fixtures; then test discovery and positive/negative OAuth/MCP behavior against a nonproduction issuer/server. Include wrong audience, unsupported grant, expired or revoked grant, another job/tenant, write tool, out-of-scope resource, and source-owner revocation. Check how current source rights affect later group-reader report access.
- Deliver a source contract, broker and worker tool inventory, fixtures/tests, observed authorization evidence, and a clear list of unrun enterprise-source gates. Enable a real source only through its approved owner process.
