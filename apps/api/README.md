# Dashboard API

Future authenticated dashboard API and internal job API. This directory is reserved for the service that accepts user requests, validates selected connections and resources, records immutable job policy, and serves job status, events, reports, and evidence to the dashboard. The [controller](../../services/controller/README.md) owns queue dispatch and OpenShell sandbox lifecycle.

The API must authenticate users with Okta Authorization Code with PKCE through a BFF session, enforce CSRF protection for mutations, and never accept `tenant_id`, `user_id`, model entitlement, or authorization scopes as trusted browser claims. A separate internal endpoint authenticates the current sandbox attempt before returning its narrow stage manifest or accepting events and artifacts. See [job lifecycle](../../docs/design/job-lifecycle.md), [identity and access](../../docs/design/identity-and-access.md), and the [OpenAPI sketch](../../contracts/openapi.yaml).

Initial endpoints to implement: job submission, listing/getting, event streaming, cancellation, connection management, and artifact retrieval. Request and output shapes begin in [contracts](../../contracts/README.md).

