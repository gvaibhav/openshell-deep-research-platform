# CR-0020: Conditional supervisor middleware route gate

- **ID:** CR-0020
- **Status:** Deferred
- **Impact ID:** DR-RUNTIME-002
- **Phase:** Conditional Phase 1 fallback after a positive SEL decision and failed preferred route proof; before private data
- **Accountable team:** OpenShell platform and security owners (proposed)
- **Component paths:** `services/supervisor-route-gate/`, `infra/openshell/middleware/`, and `contracts/internal/supervisor-route-decision.schema.json` (planned only if selected)
- **Requirement IDs:** OPS-11, RES-11, OPS-04
- **Primary design:** [Conditional middleware and surface matrix](../design/deployment-and-operations.md#private-stage-route-governance-implementation-impact)
- **Impact analysis:** [Full surface matrix](../design/deployment-and-operations.md#private-stage-route-governance-implementation-impact)
- **Paired ToDo:** [Conditional implementation and proof checklist](../todos/CR-0020-supervisor-middleware-route-gate.md)

## Current and target behavior

The preferred private route boundary is the [CR-0019](CR-0019-private-stage-route-governance.md) / [ToDo](../todos/CR-0019-private-stage-route-governance.md) gateway interceptor, authoritative profile catalog, inspected native supervisor policy, and outer CNI. The design names a separate supervisor middleware decision service **only if** live proof shows that composition cannot deny a worker's unapproved request on an otherwise reachable host. No middleware service is selected or implemented. This pair tracks the existing conditional design so its component and proof obligation cannot be mistaken for part of CR-0019 or for a current control.

If formally selected through a recorded design decision, specify and implement a fail-closed supervisor HTTP/WebSocket request decision callback. It validates the OpenShell extension JWT issuer, audience, `caller_kind=supervisor`, sandbox ID, current job/stage/attempt, recovery generation, and admitted route before every covered request. The CR-0019 interceptor must preserve mandatory `network_middlewares` attachment, host coverage, inspected TLS, and `on_error: fail_closed` against later mutation. A middleware response is an allow/deny decision, not an inline trusted response classifier or a substitute for the full-create/profile/mount/service checks. Raw TCP, `tls: skip`, WebSocket binary, and uninspectable response bodies remain excluded unless a separately qualified control is designed and tracked.

## Required behavior

- **Accept if selected:** A current bound sandbox reaches only a reviewed covered request under a valid supervisor extension identity and current route/recovery state; the callback records a bounded auditable decision. The native policy, CR-0019 mutation guard, and CNI also pass their own probes.
- **Deny if selected:** Missing/forged/wrong-audience extension JWT, wrong `caller_kind` or sandbox/attempt, stale generation, unapproved host/path/method, detached middleware, incomplete host coverage, skipped TLS inspection, callback timeout/error, and an existing connection after route revocation fail before destination dispatch. Unsupported raw or opaque routes never become private-stage exceptions through this callback.

## Dependency, risk, and disable path

Keep this pair `Deferred` until a concrete failed CR-0019 live route probe and owner decision select it; otherwise it may be withdrawn with the recorded decision. Selection requires a new review of the exact OpenShell extension schema and middleware coverage, an updated threat model, approved component owner, and a signed route-decision contract before code. If selected proof fails, disable the middleware route and keep private stages closed; do not silently fall back to a wider native policy or direct worker egress. This option cannot qualify direct-source response capture or make an ungoverned create/profile/service RPC safe.

## Closure gate

Do not mark `Verified` while deferred. If selected, the paired ToDo must link the decision, versioned request/identity contract, code/configuration PRs, exact gateway/supervisor policy and middleware attachment receipts, live allow/deny and failure-mode tests, CNI and CR-0019 results, rollback, and independent platform/security review. A separate source-response classifier, if ever needed, requires its own impact analysis and pair.
