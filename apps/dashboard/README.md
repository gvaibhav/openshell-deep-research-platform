# Research dashboard

Future user interface for Okta sign-in, selecting approved sources, choosing individual or approved Okta-group job visibility, submitting jobs, following progress, reviewing evidence-backed results, cancelling owned jobs, and managing source connections. It is outside OpenShell and calls only the authenticated dashboard API.

The UI must not embed OpenShell gateway credentials, vendor OAuth client secrets, source access tokens, or sandbox service URLs. It must not treat a disabled control as authorization. The job list shows only API-authorized jobs; a guessed URL never grants access. An approved group audience makes a job visible only to current members of that exact group, and group visibility does not bypass source permissions for the report. The API and broker enforce execution policy; the API enforces the separate [research visibility policy](../../docs/design/research-visibility.md). See [requirements](../../docs/requirements.md) and [architecture](../../docs/architecture.md).

