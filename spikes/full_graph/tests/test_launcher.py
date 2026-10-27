import contextlib
import copy
import hashlib
import io
import json
import os
import subprocess
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from spike.launcher import OpenShellCommands, ProbeFailure, run_live
from spike.policy import make_policy, policy_allows


class LauncherTests(unittest.TestCase):
    def commands(self):
        return OpenShellCommands(
            "spike-a", "worker@sha256:" + "a" * 64, "policy.yaml",
            "http://relay.spike.internal:8765/v1", "approved-model-v1",
            "/private/tmp/openshell-v0.1.5/openshell", "http://127.0.0.1:17671",
        )

    def test_policy_has_only_exact_relay_post_for_worker_python(self):
        policy = make_policy("relay.spike.internal", 8765, "/usr/local/bin/python3.13")
        self.assertTrue(policy_allows(policy, "relay.spike.internal", 8765, "POST", "/v1/chat/completions", "/usr/local/bin/python3.13"))
        self.assertFalse(policy_allows(policy, "model.example.test", 443, "POST", "/v1/chat/completions", "/usr/local/bin/python3.13"))
        self.assertFalse(policy_allows(policy, "relay.spike.internal", 8765, "GET", "/admin", "/usr/local/bin/python3.13"))
        self.assertFalse(policy_allows(policy, "relay.spike.internal", 8765, "POST", "/v1/chat/completions", "/usr/bin/curl"))
        self.assertEqual(policy["network_policies"]["model_relay"]["endpoints"][0]["enforcement"], "enforce")
        filesystem = policy["filesystem_policy"]
        self.assertTrue(filesystem["include_workdir"])
        self.assertTrue({"/opt", "/opt/spike", "/usr", "/lib", "/etc", "/proc"}.issubset(filesystem["read_only"]))
        self.assertFalse({"/opt", "/opt/spike"} & set(filesystem["read_write"]))

    def test_launcher_orders_inspection_before_worker_and_checks_denial(self):
        commands = self.commands()
        self.assertEqual(commands.create()[:7], ["/private/tmp/openshell-v0.1.5/openshell", "--gateway-endpoint", "http://127.0.0.1:17671", "sandbox", "create", "--name", "spike-a"])
        self.assertIn("--no-auto-providers", commands.create())
        self.assertEqual(commands.policy_full(), ["/private/tmp/openshell-v0.1.5/openshell", "--gateway-endpoint", "http://127.0.0.1:17671", "policy", "get", "spike-a", "--full", "--output", "json"])
        self.assertIn("--no-login-shell", commands.run_worker("stage-aurora-1"))
        self.assertIn("PYTHONPATH=/opt/spike", commands.run_worker("stage-aurora-1"))
        self.assertIn("--output", commands.policy_full())
        self.assertIn("json", commands.policy_full())
        self.assertIn("provider", commands.provider_list())
        self.assertEqual(commands.delete(), ["/private/tmp/openshell-v0.1.5/openshell", "--gateway-endpoint", "http://127.0.0.1:17671", "sandbox", "delete", "spike-a"])
        self.assertIn("1.1.1.1", " ".join(commands.denied_egress_probe()))

    def test_observed_v015_name_limit_is_enforced_before_create(self):
        with self.assertRaises(ValueError):
            OpenShellCommands("research-spike-aurora", "worker@sha256:" + "a" * 64, "policy.yaml", "http://relay.spike.internal:8765/v1", "approved-model-v1", "/private/tmp/openshell-v0.1.5/openshell", "http://127.0.0.1:17671")

    def test_explicit_isolated_cli_and_loopback_gateway_are_required(self):
        with self.assertRaises(ValueError):
            OpenShellCommands("spike-a", "worker@sha256:" + "a" * 64, "policy.yaml", "http://relay.spike.internal:8765/v1", "approved-model-v1", "openshell", "http://127.0.0.1:17671")
        with self.assertRaises(ValueError):
            OpenShellCommands("spike-a", "worker@sha256:" + "a" * 64, "policy.yaml", "http://relay.spike.internal:8765/v1", "approved-model-v1", "/private/tmp/openshell-v0.1.5/openshell", "http://gateway.example.test:17671")

    def test_direct_egress_probe_must_fail(self):
        commands = self.commands()
        commands.require_denied_egress(returncode=1, stdout="policy_denied")
        with self.assertRaises(ProbeFailure):
            commands.require_denied_egress(returncode=0, stdout="connected")

    def test_exact_json_policy_admission_and_no_provider_are_required(self):
        from spike import launcher

        policy = make_policy("relay.spike.internal", 8765)
        effective = copy.deepcopy(policy)
        effective["network_policies"]["model_relay"]["name"] = "model_relay"
        sandbox = {
            "name": "spike-a", "phase": "Ready", "policy_source": "sandbox",
            "current_policy_version": 2,
            "configuration_admission": {"state": "accepted", "policy_version": 2, "policy_hash": "a" * 64, "config_revision": 19},
            "conditions": [{"type": "Ready", "status": "True"}, {"type": "ConfigurationReady", "status": "True"}],
            "policy": effective, "endpoint_statuses": [],
        }
        revision = {"active_version": 2, "config_revision": 19, "version": 2, "hash": "a" * 64, "status": "effective", "policy_source": "sandbox", "scope": "sandbox", "sandbox": "spike-a", "policy": effective}
        self.assertEqual(launcher.inspect_runtime_policy(sandbox, revision, {"next_page_token": "", "providers": []}, policy, "spike-a")["policy_version"], 2)
        for changed in (
            {**sandbox, "configuration_admission": {**sandbox["configuration_admission"], "state": "pending"}},
            {**sandbox, "current_policy_version": 3},
            {**sandbox, "policy_source": "global"},
        ):
            with self.subTest(changed=changed), self.assertRaises(ProbeFailure):
                launcher.inspect_runtime_policy(changed, revision, {"next_page_token": "", "providers": []}, policy, "spike-a")
        widened = copy.deepcopy(revision)
        widened["policy"]["network_policies"]["other"] = {"endpoints": [{"host": "example.com", "port": 443}], "binaries": []}
        with self.assertRaises(ProbeFailure):
            launcher.inspect_runtime_policy(sandbox, widened, {"next_page_token": "", "providers": []}, policy, "spike-a")
        with self.assertRaises(ProbeFailure):
            launcher.inspect_runtime_policy(sandbox, revision, {"next_page_token": "", "providers": [{"name": "unexpected-provider"}]}, policy, "spike-a")

    def test_get_and_wrong_path_post_on_allowed_relay_host_must_be_denied(self):
        commands = self.commands()
        get_probe = commands.http_denial_probe("GET", "/v1/chat/completions")
        post_probe = commands.http_denial_probe("POST", "/v1/not-approved")
        self.assertIn("GET", " ".join(get_probe))
        self.assertIn("/v1/not-approved", " ".join(post_probe))
        compile(get_probe[-1], "<get-probe>", "exec")
        compile(post_probe[-1], "<post-probe>", "exec")
        compile(commands.read_only_probe()[-1], "<read-only-probe>", "exec")
        commands.require_http_denial(0, "OPEN_SHELL_L7_POLICY_DENIED")
        with self.assertRaises(ProbeFailure):
            commands.require_http_denial(0, "HTTP 404 from fixture stub")

    def test_http_probe_requires_structured_openshell_l7_denial_not_generic_403(self):
        code = self.commands().http_denial_probe("GET", "/v1/chat/completions")[-1]

        def run_probe(body: bytes, *, status: int = 403) -> str:
            failure = urllib.error.HTTPError(
                "http://relay.spike.internal:8765/v1/chat/completions",
                status, "synthetic", {}, io.BytesIO(body),
            )

            class FailingOpener:
                def open(self, request, timeout=5):
                    raise failure

            output = io.StringIO()
            with patch("urllib.request.build_opener", return_value=FailingOpener()), contextlib.redirect_stdout(output):
                exec(code, {})  # noqa: S102 - exercise the fixed launcher-generated probe without a socket
            return output.getvalue()

        accepted = run_probe(b'{"error":"policy_denied","policy":"model_relay","layer":"l7"}')
        self.commands().require_http_denial(0, accepted)
        for body in (
            b"<html>backend rejected request</html>",
            b'{"error":"denied","policy":"model_relay","layer":"l7"}',
            b'{"error":"policy_denied","policy":"other","layer":"l7"}',
            b'{"error":"policy_denied","policy":"model_relay","layer":"application"}',
        ):
            with self.subTest(body=body), self.assertRaises(SystemExit):
                run_probe(body)
        with self.assertRaises(ProbeFailure):
            self.commands().require_http_denial(0, "OPEN_SHELL_HTTP_DENIED")

        class DeniedSocket:
            def open(self, request, timeout=5):
                raise PermissionError("generic socket refusal")

        with patch("urllib.request.build_opener", return_value=DeniedSocket()), self.assertRaises(PermissionError):
            exec(code, {})  # noqa: S102 - exercise the fixed launcher-generated probe without a socket

    def test_live_wrong_stage_exec_precedes_graph_and_leaves_synthetic_audit_empty(self):
        from spike import launcher

        commands = self.commands()
        manifest_path = Path("spikes/full_graph/stage.example.json")
        manifest = launcher.StageManifest.load(manifest_path)
        result = {
            "stage_id": manifest.stage_id, "verified": True,
            "steps": [{"step": name} for name in ("plan", "retrieve", "synthesize", "verify")],
            "retrieval_tool_calls": [{"source_id": source_id, "decision": "allow"} for source_id in manifest.source_ids],
            "model_requests_observed": 6,
        }
        operations: list[str] = []

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit = root / "model-audit.jsonl"
            audit.touch(mode=0o600)
            policy = root / "policy.json"
            policy.write_text("{}", encoding="utf-8")
            commands = OpenShellCommands(
                commands.sandbox_name, commands.image_ref, str(policy), commands.relay_url,
                "fixture-model-v1", commands.cli_path, commands.gateway_endpoint,
            )

            def fake_run(args, **kwargs):
                operation = kwargs.get("operation", "")
                operations.append(operation)
                if operation == "preflight sandbox get":
                    return subprocess.CompletedProcess(args, 1, "", "sandbox not found")
                if operation in {"get sandbox", "get effective policy", "list attached providers"}:
                    return subprocess.CompletedProcess(args, 0, "{}", "")
                if operation == "import baked worker":
                    return subprocess.CompletedProcess(args, 0, "WORKER_IMPORT_OK:1000\n", "")
                if operation == "probe worker code read-only":
                    return subprocess.CompletedProcess(args, 0, "WORKER_CODE_READ_ONLY\n", "")
                if operation == "verify uploaded stage file":
                    digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
                    return subprocess.CompletedProcess(args, 0, f"STAGE_FILE_SHA256:{digest}\n", "")
                if operation == "probe wrong expected stage":
                    self.assertIn("sandbox", args)
                    self.assertIn("exec", args)
                    self.assertIn("spike.worker", args)
                    self.assertIn("/work/stage.json", args)
                    expected = args[args.index("--expected-stage-id") + 1]
                    self.assertNotEqual(expected, manifest.stage_id)
                    self.assertEqual(audit.read_text(encoding="utf-8"), "")
                    return subprocess.CompletedProcess(args, 2, "", "worker failed closed: StageManifestError: stage ID does not match the launcher binding\n")
                if operation == "probe unadmitted fixture source":
                    return subprocess.CompletedProcess(args, 0, json.dumps({"source_id": "decoy", "decision": "deny", "stage_id": manifest.stage_id}), "")
                if operation == "probe direct egress":
                    return subprocess.CompletedProcess(args, 1, "", "PermissionError")
                if operation.startswith("probe ") and "relay" in operation:
                    return subprocess.CompletedProcess(args, 0, "OPEN_SHELL_L7_POLICY_DENIED\n", "")
                if operation == "run in-sandbox graph":
                    self.assertEqual(audit.read_text(encoding="utf-8"), "")
                    stages = ["plan", "retrieve", "retrieve", "retrieve", "synthesize", "verify"]
                    audit.write_text("".join(json.dumps({
                        "request_number": index, "stage": stage, "model_id": "fixture-model-v1", "decision": "allow",
                    }) + "\n" for index, stage in enumerate(stages, 1)), encoding="utf-8")
                    return subprocess.CompletedProcess(args, 0, "", "")
                if operation == "download graph result":
                    Path(args[-1]).write_text(json.dumps(result), encoding="utf-8")
                return subprocess.CompletedProcess(args, 0, "", "")

            def fake_cleanup(unused_commands, observations):
                observations["delete_accepted"] = True
                observations["sandbox_absent_after_delete"] = True

            with patch("spike.launcher._assert_version", return_value="openshell 0.1.5"), patch("spike.launcher._run", side_effect=fake_run), patch("spike.launcher.inspect_runtime_policy", return_value={"provider_count": 0}), patch("spike.launcher._observe_cleanup", side_effect=fake_cleanup):
                observed = run_live(commands, manifest_path, root / "observations", synthetic_model_audit=audit)
            self.assertLess(operations.index("probe wrong expected stage"), operations.index("run in-sandbox graph"))
            self.assertTrue(observed["wrong_stage_denied"])
            self.assertTrue(observed["wrong_stage_model_audit_unchanged"])
            self.assertEqual(observed["synthetic_model_audit_request_count"], 6)

    def test_wrong_stage_probe_rejects_unexpected_failure_and_any_stub_request(self):
        from spike.launcher import run_wrong_stage_probe

        with tempfile.TemporaryDirectory() as directory:
            audit = Path(directory) / "model-audit.jsonl"
            audit.touch(mode=0o600)
            failure = subprocess.CompletedProcess([], 2, "", "worker failed closed: StageManifestError: stage ID does not match the launcher binding\n")
            with patch("spike.launcher._run", return_value=subprocess.CompletedProcess([], 1, "", "generic worker failure")), self.assertRaises(ProbeFailure):
                run_wrong_stage_probe(self.commands(), "stage-aurora-1", audit, {})

            def fake_with_request(args, **kwargs):
                audit.write_text('{"request_number":1,"stage":"plan"}\n', encoding="utf-8")
                return failure

            with patch("spike.launcher._run", side_effect=fake_with_request), self.assertRaisesRegex(ProbeFailure, "model audit"):
                run_wrong_stage_probe(self.commands(), "stage-aurora-1", audit, {})

    def test_fixture_live_run_requires_fresh_host_audit_before_cli_or_sandbox_create(self):
        original = self.commands()
        commands = OpenShellCommands(
            original.sandbox_name, original.image_ref, original.policy_file, original.relay_url,
            "fixture-model-v1", original.cli_path, original.gateway_endpoint,
        )
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("spike.launcher._assert_version", side_effect=AssertionError("CLI must not start")),
            self.assertRaisesRegex(ProbeFailure, "fresh credential-free synthetic model audit"),
        ):
            run_live(commands, Path("spikes/full_graph/stage.example.json"), Path(directory) / "observations")

    def test_single_file_upload_is_unfiltered_and_exact_file_is_checked(self):
        commands = self.commands()
        manifest_path = Path("spikes/full_graph/stage.example.json")
        self.assertIn("--no-git-ignore", commands.upload_manifest(manifest_path))
        verify = commands.verify_uploaded_manifest(manifest_path)
        self.assertIn("/work/stage.json", " ".join(verify))
        self.assertIn("STAGE_FILE_SHA256", " ".join(verify))

    def test_uncertain_create_is_reconciled_and_deleted_by_name(self):
        commands = self.commands()
        calls = []

        def fake_run(args, **kwargs):
            calls.append(args)
            if "create" in args:
                raise ProbeFailure("create failed (exit 1)")
            if "get" in args:
                return subprocess.CompletedProcess(args, 1, "", "Error: code: 'Some requested entity was not found', message: \"sandbox not found\"")
            return subprocess.CompletedProcess(args, 0, "", "")

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "attempt"
            with patch("spike.launcher._assert_version", return_value="openshell 0.1.5"), patch("spike.launcher._run", side_effect=fake_run), self.assertRaisesRegex(ProbeFailure, "create failed"):
                run_live(commands, Path("spikes/full_graph/stage.example.json"), output)
            self.assertTrue(any("delete" in command for command in calls))
            self.assertTrue(json.loads((output / "observations.json").read_text())["sandbox_absent_after_delete"])

    def test_preflight_not_found_classifier_requires_sandbox_specific_message(self):
        from spike.launcher import _is_not_found

        self.assertTrue(_is_not_found(subprocess.CompletedProcess([], 1, "", "message: sandbox not found")))
        self.assertFalse(_is_not_found(subprocess.CompletedProcess([], 1, "", "some requested entity was not found")))
        self.assertFalse(_is_not_found(subprocess.CompletedProcess([], 1, "", "gateway not found")))

    def test_command_failure_reports_safe_operation_label(self):
        from spike.launcher import _run

        with patch("spike.launcher.subprocess.run", return_value=subprocess.CompletedProcess(["openshell"], 1, "", "possibly sensitive stderr")):
            with self.assertRaisesRegex(ProbeFailure, "upload manifest failed") as caught:
                _run(["openshell", "sandbox", "upload"], operation="upload manifest")
            self.assertNotIn("possibly sensitive", str(caught.exception))

    def test_every_cli_child_gets_minimal_environment_without_exported_key(self):
        from spike.launcher import _run

        seen = []

        def fake_subprocess(args, **kwargs):
            seen.append((args, kwargs))
            return subprocess.CompletedProcess(args, 0, "", "")

        with patch.dict(os.environ, {"RESEARCH_OPENAI_API_KEY": "synthetic-canary-never-in-cli", "OPENAI_API_KEY": "second-canary", "UNRELATED_PRIVATE_VALUE": "third-canary"}), patch("spike.launcher.subprocess.run", side_effect=fake_subprocess):
            for command in (self.commands().get(), self.commands().create(), self.commands().run_worker("stage-aurora-1"), self.commands().delete()):
                _run(command, operation="synthetic CLI child")
        self.assertEqual(len(seen), 4)
        for _, kwargs in seen:
            child_env = kwargs["env"]
            self.assertEqual(set(child_env), {"PATH", "LANG"})
            self.assertEqual(child_env["PATH"], "/usr/bin:/bin:/usr/sbin:/sbin")
            self.assertNotIn("synthetic-canary-never-in-cli", str(child_env))
            self.assertNotIn("second-canary", str(child_env))
            self.assertNotIn("third-canary", str(child_env))

    def test_active_cancellation_during_delayed_plan_observes_absence_and_no_later_requests(self):
        from spike.launcher import run_active_cancellation_probe

        with tempfile.TemporaryDirectory() as directory:
            audit = Path(directory) / "model-audit.jsonl"
            audit.touch(mode=0o600)
            deleted = False
            started = []

            class PendingExec:
                returncode = None

                def __init__(self, args, **kwargs):
                    started.append((args, kwargs))
                    audit.write_text(json.dumps({"request_number": 1, "stage": "plan", "model_id": "approved-model-v1", "effective_tools": [], "decision": "allow", "response_delay_seconds": 5}) + "\n", encoding="utf-8")

                def poll(self):
                    return 1 if deleted else None

                def communicate(self, timeout=None):
                    self.returncode = 1
                    return "", ""

                def terminate(self):
                    self.returncode = -15

                def kill(self):
                    self.returncode = -9

            def fake_cleanup(commands, observations):
                nonlocal deleted
                deleted = True
                observations["delete_accepted"] = True
                observations["sandbox_absent_after_delete"] = True

            observations = {}
            with patch("spike.launcher.subprocess.Popen", PendingExec), patch("spike.launcher._observe_cleanup", side_effect=fake_cleanup), patch("spike.launcher.time.sleep"):
                run_active_cancellation_probe(self.commands(), "stage-aurora-1", audit, observations)
            self.assertTrue(observations["active_cancellation_observed"])
            self.assertEqual(observations["model_requests_total_after_cancel_wait"], 1)
            self.assertEqual(observations["new_model_requests_after_cancel"], 0)
            self.assertNotIn("model_requests_after_cancel", observations)
            self.assertEqual(observations["later_retrieval_requests"], 0)
            self.assertEqual(started[0][0], self.commands().run_worker("stage-aurora-1"))
            self.assertNotIn("RESEARCH_OPENAI_API_KEY", started[0][1]["env"])

    def test_active_cancellation_rejects_later_retrieval_request(self):
        from spike.launcher import run_active_cancellation_probe

        with tempfile.TemporaryDirectory() as directory:
            audit = Path(directory) / "model-audit.jsonl"
            audit.touch(mode=0o600)

            class PendingExec:
                returncode = 1

                def __init__(self, args, **kwargs):
                    audit.write_text(json.dumps({"request_number": 1, "stage": "plan", "model_id": "approved-model-v1", "effective_tools": [], "decision": "allow", "response_delay_seconds": 5}) + "\n", encoding="utf-8")

                def poll(self):
                    return None

                def communicate(self, timeout=None):
                    return "", ""

                def terminate(self):
                    pass

                def kill(self):
                    pass

            def fake_cleanup(commands, observations):
                observations["sandbox_absent_after_delete"] = True
                audit.write_text(audit.read_text(encoding="utf-8") + json.dumps({"request_number": 2, "stage": "retrieve", "model_id": "approved-model-v1", "effective_tools": ["read_fixture"], "decision": "allow", "response_delay_seconds": 0}) + "\n", encoding="utf-8")

            with patch("spike.launcher.subprocess.Popen", PendingExec), patch("spike.launcher._observe_cleanup", side_effect=fake_cleanup), patch("spike.launcher.time.sleep"), self.assertRaisesRegex(ProbeFailure, "later model or fixture"):
                run_active_cancellation_probe(self.commands(), "stage-aurora-1", audit, {})

    def test_worker_failure_keeps_exception_kind_without_raw_stderr(self):
        from spike.launcher import safe_worker_error_kind

        raw = "Traceback (most recent call last):\n  File 'worker.py', line 1\nopenai.APIConnectionError: prompt and credential must stay private\n"
        self.assertEqual(safe_worker_error_kind(raw), "APIConnectionError")
        self.assertEqual(safe_worker_error_kind("sensitive output without an exception"), "unclassified")


if __name__ == "__main__":
    unittest.main()
