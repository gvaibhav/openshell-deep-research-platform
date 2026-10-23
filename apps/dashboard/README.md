# Research dashboard

Future user interface for Okta sign-in, selecting approved sources, submitting jobs, following progress, reviewing evidence-backed results, cancelling jobs, and managing source connections. It is outside OpenShell and calls only the authenticated dashboard API.

The UI must not embed OpenShell gateway credentials, vendor OAuth client secrets, source access tokens, or sandbox service URLs. It must not treat a disabled control as authorization. The API and broker enforce the job policy. See [requirements](../../docs/requirements.md) and [architecture](../../docs/architecture.md).

