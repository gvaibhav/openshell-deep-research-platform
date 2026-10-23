# Job controller

Future trusted service outside OpenShell. It claims durable queue work, performs admission reconciliation, creates and deletes version-pinned worker sandboxes through the OpenShell SDK, issues one stage manifest and workload identity per attempt, fences stale attempts, and commits terminal state only after results pass validation.

It authenticates to the OpenShell gateway as a dedicated machine principal. It does not pass that credential to workers. The controller checks the **effective** OpenShell policy after provider attachment, enforces budgets and deadlines from durable state, and reaps orphaned sandboxes. See [job lifecycle](../../docs/design/job-lifecycle.md), [architecture](../../docs/architecture.md), and [identity and access](../../docs/design/identity-and-access.md).
