# ToDo for CR-0020: Conditional supervisor middleware route gate

- **ID:** CR-0020
- **Status:** Deferred
- **Impact ID:** DR-RUNTIME-002
- **Phase:** Conditional Phase 1 fallback before private data
- **Accountable team:** OpenShell platform and security owners (proposed)
- **Component paths:** Planned `services/supervisor-route-gate/`, `infra/openshell/middleware/`, `contracts/internal/supervisor-route-decision.schema.json`, and allow/deny examples; select exact paths only after a recorded fallback decision
- **Requirement IDs:** OPS-11, RES-11, OPS-04
- **Change request:** [CR-0020](../change-requests/CR-0020-supervisor-middleware-route-gate.md)
- **Primary design:** [Conditional fallback and impact matrix](../design/deployment-and-operations.md#private-stage-route-governance-implementation-impact)

## Conditional implementation and proof checklist

- [ ] Remain `Deferred` while [CR-0019](../change-requests/CR-0019-private-stage-route-governance.md) / [ToDo](CR-0019-private-stage-route-governance.md) preferred route proof has not failed. Record the exact failed shared-host/path case and owner decision before selecting this component; rerun the design impact gate if the target scope changes. A recorded decision may instead withdraw this option and remove the abandoned design path.
- [ ] If selected, pin the deployed OpenShell gateway/supervisor extension JWT and middleware schema versions, exact covered HTTP/WebSocket hosts and TLS modes, callback timeout/error behavior, signing/trust roots, service identity, and default-deny deployment topology.
- [ ] Before component code, write `contracts/internal/supervisor-route-decision.schema.json` and allowed/denied examples for issuer/audience/`caller_kind=supervisor`/sandbox/attempt/recovery-generation binding and exact host/path/method decision. Specify `on_error: fail_closed` and an auditable bounded result.
- [ ] Write failing tests for valid covered request, wrong/forged extension identity, stale generation, wrong sandbox or attempt, unapproved path on an otherwise allowed host, detached or altered middleware configuration, timeout/error, established connection after revocation, and unsupported raw TCP/`tls: skip`/binary WebSocket/opaque response paths.
- [ ] Implement the callback and make [CR-0019](../change-requests/CR-0019-private-stage-route-governance.md) mutation governance preserve its mandatory attachment, host coverage, inspected TLS, and fail-closed behavior. Keep the full-create/profile/mount/service, native policy, and CNI gates separate and mandatory.
- [ ] Prove live on pinned gateway/supervisor/node/CNI versions that valid private traffic succeeds and every denied case fails **before** destination dispatch, including callback outage. Retain exact receipts, request/decision audits without sensitive content, image/SBOM/CVE evidence, rollback drill, and independent platform/security review.

## Completion evidence

- **Selection:** Not selected; no recorded failed preferred route proof. Status remains `Deferred`.
- **Contracts, code, CI, and live evidence:** None. This ToDo is a conditional obligation, not an implemented control or a substitute for [CR-0019](../change-requests/CR-0019-private-stage-route-governance.md).
- **Disable path:** Keep private stages closed if the preferred route composition fails and this fallback has not passed its own live proof. No unreviewed widening or direct worker path is allowed.
