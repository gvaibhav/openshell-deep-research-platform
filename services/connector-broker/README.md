# Connector MCP broker

Future trusted service outside OpenShell. It authenticates the sandbox job identity, loads the server-held job policy, validates each tool and its arguments, obtains the correct user or application grant for the requested source, calls the upstream MCP server or API, and records auditable provenance.

It is intentionally a narrow tool service, not another research agent. Provider tokens and refresh credentials stay in its vault or cloud identity system. See [MCP connector design](../../docs/design/mcp-connector-broker.md) and [identity and access](../../docs/design/identity-and-access.md).

