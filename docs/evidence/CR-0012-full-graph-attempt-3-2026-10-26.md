# CR-0012: corrected launcher, model tool-catalog denial

- **Date:** 2026-10-26
- **Data:** Synthetic Aurora fixture and credential-free model stub only.
- **Runtime/image:** Isolated OpenShell v0.1.5 Docker gateway; rebuilt development worker `localhost/openshell-research-spike@sha256:c2dc55e0c111f755282c090c11ada8252f897bf3f6a54486493f1041b5a3e609`.
- **Status:** Failed closed at the first graph model request; the effective tool registry still contained an unapproved Deep Agents `delete` tool. This is not complete graph proof.

The corrected launcher created `spike-aurora-3`, observed `Ready`, parsed the exact v0.1.5 effective policy hash `6bb7a0fb07ef644f58b9d8243bfd875b458c74c3bf6f64d218f1c30c7d3b37da` and accepted config revision, and observed zero attached providers. It verified read-only baked-code access, imported the worker, uploaded and hash-checked a regular stage file, denied direct IP egress, and received OpenShell L7 `policy_denied` for GET and wrong-path POST on the allowed relay host. The in-worker unadmitted fixture source probe denied as expected.

The worker `sandbox exec` then failed. A second disposable sandbox with the same image and policy reproduced HTTP 403 at the first plan model call. A temporary synthetic-only response hook showed that the POST reached the fixture model at the exact `/v1/chat/completions` path and advertised tool names `['delete']`. The fixture model returned `effective tool catalog differs from the fixed stage`; this was an application tool-registry denial, not an OpenShell route denial. Deep Agents 0.7.32 had inserted its built-in `delete` tool despite the original exclusion list. No successful model request was logged and no research result was written.

The launcher accepted deletion and observed `spike-aurora-3` absent; the manual diagnosis sandbox `spike-debug-3` was also deleted and observed absent. Sanitized policy/provider/observation files remain temporarily at `/private/tmp/cr0012-live-20261026-3/observations/`; no prompt or credential was copied into this evidence record.

The worker agent is adding `delete` to the excluded tool registry with a red/green test and retaining the exact fixture model tool-catalog gate. Rerun a newly built image to prove actual allowed `read_fixture` calls, model-request count, four stages, and citation verification. Cancellation, copied-identity denial, real-model ingress, restricted comparator/CNI, and final-image CVE disposition remain open. See [CR-0012](../change-requests/CR-0012-full-graph-runtime-spike.md) and its [ToDo](../todos/CR-0012-full-graph-runtime-spike.md).
