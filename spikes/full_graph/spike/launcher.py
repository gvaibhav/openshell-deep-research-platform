"""Small host-side OpenShell CLI launcher; no agent graph or source handling."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from spike.contract import StageManifest
from spike.policy import write_policy


class ProbeFailure(RuntimeError):
    """An OpenShell boundary observation was absent or contradicted expectation."""


_NAME = re.compile(r"^[a-z][a-z0-9-]*[a-z0-9]$")
_DIGEST_IMAGE = re.compile(r"^[A-Za-z0-9./:_-]+@sha256:[0-9a-f]{64}$")
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{1,127}$")
_CLI_CHILD_ENV = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "C"}


def _cli_child_env() -> dict[str, str]:
    """Keep host model/source credentials out of every OpenShell CLI child."""
    return dict(_CLI_CHILD_ENV)


@dataclass(frozen=True)
class OpenShellCommands:
    sandbox_name: str
    image_ref: str
    policy_file: str
    relay_url: str
    model_id: str
    cli_path: str
    gateway_endpoint: str

    def __post_init__(self) -> None:
        if not _NAME.fullmatch(self.sandbox_name) or not 3 <= len(self.sandbox_name) <= 19:
            raise ValueError("invalid disposable sandbox name (OpenShell v0.1.5 maximum: 19 characters)")
        if not _DIGEST_IMAGE.fullmatch(self.image_ref):
            raise ValueError("worker image must use an immutable sha256 digest")
        if self.model_id and not _MODEL_ID.fullmatch(self.model_id):
            raise ValueError("invalid exact model ID")
        relay = urlparse(self.relay_url)
        if relay.scheme != "http" or not relay.hostname or relay.port is None or relay.path.rstrip("/") != "/v1" or relay.username or relay.password or relay.query or relay.fragment:
            raise ValueError("disposable relay must be one exact HTTP /v1 origin")
        if not Path(self.cli_path).is_absolute() or Path(self.cli_path).name != "openshell":
            raise ValueError("an explicit absolute OpenShell CLI path is required")
        endpoint = urlparse(self.gateway_endpoint)
        try:
            address = ipaddress.ip_address(endpoint.hostname or "")
        except ValueError as error:
            raise ValueError("disposable gateway endpoint must be loopback") from error
        if endpoint.scheme != "http" or not address.is_loopback or endpoint.port is None or endpoint.path not in ("", "/") or endpoint.query or endpoint.fragment or endpoint.username or endpoint.password:
            raise ValueError("disposable gateway endpoint must be an explicit loopback HTTP URL")

    def _prefix(self) -> list[str]:
        return [self.cli_path, "--gateway-endpoint", self.gateway_endpoint]

    def create(self) -> list[str]:
        return [*self._prefix(), "sandbox", "create", "--name", self.sandbox_name, "--from", self.image_ref, "--policy", self.policy_file, "--no-auto-providers", "--detach", "--output", "json", "--", "/bin/sleep", "3600"]

    def get(self) -> list[str]:
        return [*self._prefix(), "sandbox", "get", self.sandbox_name, "--output", "json"]

    def policy_full(self) -> list[str]:
        return [*self._prefix(), "policy", "get", self.sandbox_name, "--full", "--output", "json"]

    def provider_list(self) -> list[str]:
        return [*self._prefix(), "sandbox", "provider", "list", self.sandbox_name, "--output", "json"]

    def upload_manifest(self, source: Path) -> list[str]:
        return [*self._prefix(), "sandbox", "upload", "--no-git-ignore", self.sandbox_name, str(source), "/work/stage.json"]

    def verify_uploaded_manifest(self, source: Path) -> list[str]:
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        code = (
            "from pathlib import Path; import hashlib; "
            "p=Path('/work/stage.json'); "
            "assert p.is_file() and not p.is_symlink(), 'STAGE_FILE_INVALID'; "
            f"assert hashlib.sha256(p.read_bytes()).hexdigest() == {digest!r}, 'STAGE_FILE_HASH_MISMATCH'; "
            "print('STAGE_FILE_SHA256:' + hashlib.sha256(p.read_bytes()).hexdigest())"
        )
        return [*self._prefix(), "sandbox", "exec", "-n", self.sandbox_name, "--no-login-shell", "--", "/usr/local/bin/python3.13", "-c", code]

    def run_worker(self, expected_stage_id: str) -> list[str]:
        if not self.relay_url or not self.model_id:
            raise ValueError("relay URL and exact model ID are required before running worker")
        return [
            *self._prefix(), "sandbox", "exec", "-n", self.sandbox_name, "--no-login-shell", "--env", "PYTHONPATH=/opt/spike", "--",
            "/usr/local/bin/python3.13", "-m", "spike.worker",
            "--manifest", "/work/stage.json",
            "--expected-stage-id", expected_stage_id,
            "--relay-url", self.relay_url,
            "--model-id", self.model_id,
            "--result", "/work/result.json",
            "--claimed-mode", "openshell",
        ]

    def wrong_stage_probe(self, admitted_stage_id: str) -> list[str]:
        """Run the same baked entrypoint against the admitted file with a wrong binding."""
        wrong_id = "wrong-stage-probe-v1" if admitted_stage_id != "wrong-stage-probe-v1" else "wrong-stage-probe-v2"
        return self.run_worker(wrong_id)

    def source_denial_probe(self, expected_stage_id: str, source_id: str = "decoy") -> list[str]:
        return [
            *self._prefix(), "sandbox", "exec", "-n", self.sandbox_name, "--no-login-shell", "--env", "PYTHONPATH=/opt/spike", "--",
            "/usr/local/bin/python3.13", "-m", "spike.worker",
            "--manifest", "/work/stage.json", "--expected-stage-id", expected_stage_id,
            "--relay-url", self.relay_url, "--model-id", self.model_id,
            "--result", "-", "--claimed-mode", "openshell", "--probe-source-id", source_id,
        ]

    def worker_import_probe(self) -> list[str]:
        code = "import os, spike.worker; print('WORKER_IMPORT_OK:' + str(os.getuid()))"
        return [*self._prefix(), "sandbox", "exec", "-n", self.sandbox_name, "--no-login-shell", "--env", "PYTHONPATH=/opt/spike", "--", "/usr/local/bin/python3.13", "-c", code]

    def read_only_probe(self) -> list[str]:
        code = (
            "from pathlib import Path; import os; "
            "p=Path('/opt/spike/__landlock_probe_' + str(os.getpid())); "
            "\ntry:\n p.write_text('synthetic probe')\nexcept PermissionError:\n print('WORKER_CODE_READ_ONLY')"
            "\nelse:\n p.unlink(); raise SystemExit('worker code unexpectedly writable')"
        )
        return [*self._prefix(), "sandbox", "exec", "-n", self.sandbox_name, "--no-login-shell", "--", "/usr/local/bin/python3.13", "-c", code]

    def http_denial_probe(self, method: str, path: str) -> list[str]:
        if (method, path) not in {("GET", "/v1/chat/completions"), ("POST", "/v1/not-approved")}:
            raise ValueError("unsupported synthetic HTTP denial probe")
        origin = self.relay_url.removesuffix("/v1").rstrip("/")
        request_data = "b'{}'" if method == "POST" else "None"
        code = (
            "import json, urllib.request, urllib.error\n"
            f"request=urllib.request.Request({(origin + path)!r}, data={request_data}, method={method!r})\n"
            "opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))\n"
            "try:\n"
            " with opener.open(request, timeout=5):\n  raise SystemExit('HTTP_ROUTE_REACHED')\n"
            "except urllib.error.HTTPError as error:\n"
            " if error.code != 403:\n  raise SystemExit('WRONG_HTTP_STATUS:' + str(error.code))\n"
            " body=error.read(1025)\n"
            " try:\n  denial=json.loads(body)\n"
            " except ValueError:\n  raise SystemExit('UNQUALIFIED_HTTP_403') from None\n"
            " if len(body)>1024 or not isinstance(denial, dict) or "
            "denial.get('error')!='policy_denied' or denial.get('policy')!='model_relay' or "
            "denial.get('layer')!='l7':\n  raise SystemExit('UNQUALIFIED_HTTP_403')\n"
            " print('OPEN_SHELL_L7_POLICY_DENIED')"
        )
        return [*self._prefix(), "sandbox", "exec", "-n", self.sandbox_name, "--no-login-shell", "--", "/usr/local/bin/python3.13", "-c", code]

    @staticmethod
    def require_http_denial(returncode: int, stdout: str) -> None:
        if returncode != 0 or "OPEN_SHELL_L7_POLICY_DENIED" not in stdout.splitlines():
            raise ProbeFailure("HTTP method or path denial was not observed")

    def denied_egress_probe(self) -> list[str]:
        probe = "import socket; socket.create_connection(('1.1.1.1', 443), 3)"
        return [*self._prefix(), "sandbox", "exec", "-n", self.sandbox_name, "--no-login-shell", "--", "/usr/local/bin/python3.13", "-c", probe]

    def require_denied_egress(self, returncode: int, stdout: str) -> None:
        if returncode == 0 or not any(marker in stdout for marker in ("policy_denied", "PermissionError", "Operation not permitted")):
            raise ProbeFailure("direct egress denial was not observed")

    def download_result(self, destination: Path) -> list[str]:
        return [*self._prefix(), "sandbox", "download", self.sandbox_name, "/work/result.json", str(destination)]

    def delete(self) -> list[str]:
        return [*self._prefix(), "sandbox", "delete", self.sandbox_name]


def _run(args: list[str], *, operation: str = "OpenShell command", timeout: int = 120, allowed_failure: bool = False) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=False, env=_cli_child_env())
    except subprocess.TimeoutExpired as error:
        raise ProbeFailure(f"{operation} timed out after {timeout}s") from error
    except OSError as error:
        raise ProbeFailure(f"{operation} could not start") from error
    if result.returncode and not allowed_failure:
        # Stderr could contain provider data; omit it from ordinary evidence.
        raise ProbeFailure(f"{operation} failed (exit {result.returncode})")
    return result


def _parse_json_output(raw: str, operation: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ProbeFailure(f"{operation} returned invalid JSON") from error
    if not isinstance(value, dict):
        raise ProbeFailure(f"{operation} returned a non-object JSON value")
    return value


def _is_not_found(result: subprocess.CompletedProcess[str]) -> bool:
    return result.returncode != 0 and re.search(r"\bsandbox not found\b", result.stderr, re.IGNORECASE) is not None


def safe_worker_error_kind(stderr: str) -> str:
    """Retain only a traceback exception class, never prompts or headers."""
    for line in reversed(stderr.splitlines()):
        match = re.match(r"^(?:[A-Za-z_][A-Za-z0-9_]*\.)*([A-Za-z_][A-Za-z0-9_]*(?:Error|Exception|Failure))(?::|$)", line.strip())
        if match:
            return match.group(1)
    return "unclassified"


def inspect_runtime_policy(
    sandbox: dict[str, Any],
    revision: dict[str, Any],
    providers: dict[str, Any],
    authored: dict[str, Any],
    sandbox_name: str,
) -> dict[str, Any]:
    """Fail closed on v0.1.5 structured admission, policy, or provider drift."""
    if sandbox.get("name") != sandbox_name or sandbox.get("phase") != "Ready":
        raise ProbeFailure("sandbox identity or readiness differs from the admitted attempt")
    conditions = sandbox.get("conditions")
    if not isinstance(conditions, list) or {item.get("type"): item.get("status") for item in conditions if isinstance(item, dict)}.get("Ready") != "True" or {item.get("type"): item.get("status") for item in conditions if isinstance(item, dict)}.get("ConfigurationReady") != "True":
        raise ProbeFailure("sandbox readiness conditions are not accepted")
    admission = sandbox.get("configuration_admission")
    if not isinstance(admission, dict) or admission.get("state") != "accepted" or admission.get("error") not in (None, ""):
        raise ProbeFailure("sandbox configuration admission was not accepted")
    version = admission.get("policy_version")
    digest = admission.get("policy_hash")
    config_revision = admission.get("config_revision")
    if type(version) is not int or version < 1 or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest) or type(config_revision) is not int:
        raise ProbeFailure("sandbox admission policy identity is incomplete")
    if sandbox.get("current_policy_version") != version or sandbox.get("policy_source") != "sandbox" or sandbox.get("endpoint_statuses") != []:
        raise ProbeFailure("sandbox loaded policy or endpoint state differs from admission")
    if revision.get("sandbox") != sandbox_name or revision.get("scope") != "sandbox" or revision.get("status") != "effective" or revision.get("policy_source") != "sandbox":
        raise ProbeFailure("effective policy status or source is unqualified")
    if revision.get("version") != version or revision.get("active_version") != version or revision.get("config_revision") != config_revision or revision.get("hash") != digest:
        raise ProbeFailure("effective policy revision does not match admitted configuration")
    if providers != {"next_page_token": "", "providers": []}:
        raise ProbeFailure("unexpected provider attachment or incomplete provider page")
    effective = revision.get("policy")
    if not isinstance(effective, dict) or sandbox.get("policy") != effective or effective.get("version") != 1:
        raise ProbeFailure("effective policy payload differs from sandbox configuration")
    if set(effective) - {"version", "filesystem_policy", "landlock", "process", "network_policies", "network_middlewares"}:
        raise ProbeFailure("effective policy contains an unexpected top-level section")
    if effective.get("network_middlewares") not in (None, {}):
        raise ProbeFailure("unexpected network middleware in effective policy")
    if effective.get("process") not in (None, {}):
        raise ProbeFailure("unexpected process override in effective policy")
    if effective.get("landlock") != authored.get("landlock"):
        raise ProbeFailure("effective Landlock requirement differs from initial policy")
    filesystem = effective.get("filesystem_policy")
    intended_fs = authored.get("filesystem_policy")
    if not isinstance(filesystem, dict) or not isinstance(intended_fs, dict) or filesystem.get("include_workdir") is not True:
        raise ProbeFailure("effective filesystem policy is incomplete")
    if set(filesystem) != {"include_workdir", "read_only", "read_write"}:
        raise ProbeFailure("effective filesystem policy has unexpected fields")
    read_only = filesystem.get("read_only")
    read_write = filesystem.get("read_write")
    if not isinstance(read_only, list) or not isinstance(read_write, list) or not all(isinstance(path, str) for path in read_only + read_write):
        raise ProbeFailure("effective filesystem paths are invalid")
    baseline_only = {"/bin", "/app"}
    if not set(intended_fs["read_only"]).issubset(read_only) or not set(read_only).issubset(set(intended_fs["read_only"]) | baseline_only) or set(read_write) != set(intended_fs["read_write"]):
        raise ProbeFailure("effective filesystem grants differ from the bounded initial policy")
    policies = effective.get("network_policies")
    intended_rule = authored.get("network_policies", {}).get("model_relay")
    if not isinstance(policies, dict) or set(policies) != {"model_relay"} or not isinstance(intended_rule, dict):
        raise ProbeFailure("effective network policy is not the one exact relay rule")
    relay_rule = policies["model_relay"]
    if not isinstance(relay_rule, dict) or set(relay_rule) - {"name", "endpoints", "binaries"} or relay_rule.get("name", "model_relay") != "model_relay":
        raise ProbeFailure("effective relay rule contains unexpected fields")
    if relay_rule.get("endpoints") != intended_rule["endpoints"] or relay_rule.get("binaries") != intended_rule["binaries"]:
        raise ProbeFailure("effective relay route differs from the exact initial rule")
    return {"policy_version": version, "policy_hash": digest, "config_revision": config_revision, "provider_count": 0, "policy_source": "sandbox"}


def _assert_version(commands: OpenShellCommands) -> str:
    if not Path(commands.cli_path).is_file():
        raise ProbeFailure("isolated OpenShell CLI is missing")
    observed = _run([commands.cli_path, "--version"], operation="inspect CLI version", timeout=10).stdout.strip()
    if "0.1.5" not in observed:
        raise ProbeFailure("the disposable launcher requires OpenShell CLI 0.1.5")
    return observed


def _observe_cleanup(commands: OpenShellCommands, observations: dict[str, Any]) -> None:
    """Reconcile an uncertain create by the preflight-absent disposable name."""
    try:
        deleted = _run(commands.delete(), operation="delete sandbox", timeout=120, allowed_failure=True)
        observations["delete_accepted"] = deleted.returncode == 0
    except ProbeFailure as error:
        observations["delete_accepted"] = False
        observations["cleanup_error"] = str(error)
    absent = False
    for _ in range(20):
        try:
            check = _run(commands.get(), operation="observe sandbox absence", timeout=20, allowed_failure=True)
        except ProbeFailure as error:
            observations["cleanup_error"] = str(error)
            break
        if _is_not_found(check):
            absent = True
            break
        if check.returncode != 0:
            observations["cleanup_error"] = "observe sandbox absence returned an unclassified error"
            break
        time.sleep(1)
    observations["sandbox_absent_after_delete"] = absent
    if not absent:
        observations["live_conformance"] = "failed: sandbox deletion not observed"


def _read_synthetic_model_audit(path: Path) -> list[dict[str, Any]]:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 65_536:
        raise ProbeFailure("synthetic model audit is missing or too large")
    try:
        rows = [_parse_json_output(line, "synthetic model audit") for line in path.read_text(encoding="utf-8").splitlines()]
    except (OSError, UnicodeError) as error:
        raise ProbeFailure("synthetic model audit is unreadable") from error
    if len(rows) > 32:
        raise ProbeFailure("synthetic model audit exceeds the request bound")
    return rows


_WRONG_STAGE_ERROR = "worker failed closed: StageManifestError: stage ID does not match the launcher binding"


def run_wrong_stage_probe(
    commands: OpenShellCommands,
    admitted_stage_id: str,
    audit_file: Path | None,
    observations: dict[str, Any],
) -> None:
    """Require the baked worker to reject a wrong binding before any model call."""
    baseline = _read_synthetic_model_audit(audit_file) if audit_file is not None else None
    if baseline:
        raise ProbeFailure("synthetic model audit was not fresh before wrong-stage probe")
    denied = _run(commands.wrong_stage_probe(admitted_stage_id), operation="probe wrong expected stage", timeout=60, allowed_failure=True)
    if denied.returncode != 2 or denied.stdout.strip() or len(denied.stderr) > 4096 or _WRONG_STAGE_ERROR not in denied.stderr.splitlines():
        raise ProbeFailure("wrong expected-stage manifest denial was not observed")
    if audit_file is not None:
        if _read_synthetic_model_audit(audit_file) != baseline:
            raise ProbeFailure("synthetic model audit changed during wrong-stage probe")
        observations["wrong_stage_model_audit_unchanged"] = True
    observations["wrong_stage_denied"] = True


def run_active_cancellation_probe(
    commands: OpenShellCommands,
    stage_id: str,
    audit_file: Path,
    observations: dict[str, Any],
    *,
    ready_timeout_seconds: float = 30,
) -> None:
    """Delete a sandbox while the credential-free stub holds its first reply."""
    if _read_synthetic_model_audit(audit_file):
        raise ProbeFailure("synthetic model audit was not fresh for cancellation")
    try:
        process = subprocess.Popen(
            commands.run_worker(stage_id), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=_cli_child_env(),
        )
    except OSError as error:
        raise ProbeFailure("start cancellable worker exec failed") from error
    first_event: dict[str, Any] | None = None
    try:
        deadline = time.monotonic() + ready_timeout_seconds
        while time.monotonic() < deadline:
            events = _read_synthetic_model_audit(audit_file)
            if events:
                if len(events) != 1:
                    raise ProbeFailure("later model or fixture calls appeared before cancellation")
                event = events[0]
                delay = event.get("response_delay_seconds")
                if (
                    event.get("request_number") != 1
                    or event.get("stage") != "plan"
                    or event.get("model_id") != commands.model_id
                    or event.get("effective_tools") != []
                    or event.get("decision") != "allow"
                    or not isinstance(delay, (int, float))
                    or isinstance(delay, bool)
                    or not 5 <= delay <= 30
                    or process.poll() is not None
                ):
                    raise ProbeFailure("delayed first plan request was not active and bounded")
                first_event = event
                observations["active_plan_request_observed"] = True
                break
            if process.poll() is not None:
                raise ProbeFailure("worker exec exited before the delayed plan request")
            time.sleep(0.1)
        if first_event is None:
            raise ProbeFailure("delayed plan request was not observed before timeout")
    finally:
        # A pending model reply is never left with a live worker after a failed
        # observation. The parent run_live finally retries absence if needed.
        _observe_cleanup(commands, observations)
        try:
            process.communicate(timeout=10)
        except subprocess.TimeoutExpired as error:
            process.terminate()
            try:
                process.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=3)
            observations["worker_exec_stopped_after_delete"] = False
            raise ProbeFailure("worker exec did not stop after sandbox deletion") from error
        observations["worker_exec_stopped_after_delete"] = process.returncode is not None and process.returncode != 0
    if not observations.get("sandbox_absent_after_delete") or not observations["worker_exec_stopped_after_delete"]:
        raise ProbeFailure("active cancellation did not stop the worker and observe sandbox absence")
    assert first_event is not None
    time.sleep(first_event["response_delay_seconds"] + 2)
    events_after = _read_synthetic_model_audit(audit_file)
    observations["model_requests_total_after_cancel_wait"] = len(events_after)
    observations["new_model_requests_after_cancel"] = max(0, len(events_after) - 1)
    observations["later_retrieval_requests"] = sum(event.get("stage") == "retrieve" for event in events_after[1:])
    if events_after != [first_event]:
        raise ProbeFailure("later model or fixture calls were observed after cancellation")
    observations["active_cancellation_observed"] = True
    observations["live_conformance"] = "partial: local synthetic active cancellation and absence observed"


def run_live(
    commands: OpenShellCommands,
    manifest_path: Path,
    output_dir: Path,
    *,
    synthetic_model_audit: Path | None = None,
    cancel_model_audit: Path | None = None,
) -> dict[str, Any]:
    """Run one synthetic attempt, retain sanitized observations, always delete."""
    manifest = StageManifest.load(manifest_path)
    output_dir.mkdir(parents=True, exist_ok=False)
    observations: dict[str, Any] = {"gateway_endpoint": commands.gateway_endpoint, "sandbox_name": commands.sandbox_name, "live_conformance": "unverified"}
    create_attempted = False
    try:
        if synthetic_model_audit is not None and cancel_model_audit is not None and synthetic_model_audit != cancel_model_audit:
            raise ProbeFailure("synthetic model audit paths disagree")
        audit_file = synthetic_model_audit or cancel_model_audit
        if commands.model_id == "fixture-model-v1":
            if audit_file is None:
                raise ProbeFailure("fresh credential-free synthetic model audit is required")
            if _read_synthetic_model_audit(audit_file):
                raise ProbeFailure("synthetic model audit was not fresh before sandbox creation")
        elif audit_file is not None:
            raise ProbeFailure("synthetic model audit requires the fixture model")
        observations["cli_version"] = _assert_version(commands)
        preflight = _run(commands.get(), operation="preflight sandbox get", timeout=20, allowed_failure=True)
        if preflight.returncode == 0:
            raise ProbeFailure("disposable sandbox name already exists")
        if not _is_not_found(preflight):
            raise ProbeFailure("preflight sandbox absence could not be established")
        create_attempted = True
        _run(commands.create(), operation="create sandbox", timeout=180)
        sandbox_raw = _run(commands.get(), operation="get sandbox").stdout
        policy_raw = _run(commands.policy_full(), operation="get effective policy").stdout
        providers_raw = _run(commands.provider_list(), operation="list attached providers").stdout
        sandbox = _parse_json_output(sandbox_raw, "get sandbox")
        policy = _parse_json_output(policy_raw, "get effective policy")
        providers = _parse_json_output(providers_raw, "list attached providers")
        authored = _parse_json_output(Path(commands.policy_file).read_text(encoding="utf-8"), "authored policy")
        observations["policy_inspection"] = inspect_runtime_policy(sandbox, policy, providers, authored, commands.sandbox_name)
        (output_dir / "sandbox-get.json").write_text(sandbox_raw, encoding="utf-8")
        (output_dir / "effective-policy.json").write_text(policy_raw, encoding="utf-8")
        (output_dir / "providers.json").write_text(providers_raw, encoding="utf-8")
        imported = _run(commands.worker_import_probe(), operation="import baked worker")
        if "WORKER_IMPORT_OK:1000" not in imported.stdout.splitlines():
            raise ProbeFailure("baked worker import or UID was not observed")
        observations["baked_worker_imported"] = True
        read_only = _run(commands.read_only_probe(), operation="probe worker code read-only")
        if "WORKER_CODE_READ_ONLY" not in read_only.stdout.splitlines():
            raise ProbeFailure("baked worker code was not observed read-only")
        observations["baked_code_read_only"] = True
        _run(commands.upload_manifest(manifest_path), operation="upload stage manifest")
        uploaded = _run(commands.verify_uploaded_manifest(manifest_path), operation="verify uploaded stage file")
        expected_file_marker = "STAGE_FILE_SHA256:" + hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        if expected_file_marker not in uploaded.stdout.splitlines():
            raise ProbeFailure("uploaded stage is not the exact regular file")
        observations["stage_file_sha256"] = expected_file_marker.removeprefix("STAGE_FILE_SHA256:")
        run_wrong_stage_probe(commands, manifest.stage_id, audit_file, observations)
        source_probe = _run(commands.source_denial_probe(manifest.stage_id), operation="probe unadmitted fixture source")
        source_denial = _parse_json_output(source_probe.stdout, "unadmitted fixture source probe")
        if source_denial != {"source_id": "decoy", "decision": "deny", "stage_id": manifest.stage_id}:
            raise ProbeFailure("unadmitted fixture source denial was not observed")
        observations["unadmitted_source_denied"] = True
        denied = _run(commands.denied_egress_probe(), operation="probe direct egress", allowed_failure=True)
        commands.require_denied_egress(denied.returncode, denied.stdout + denied.stderr)
        observations["direct_egress_denied"] = True
        for method, path, label in (("GET", "/v1/chat/completions", "GET on relay"), ("POST", "/v1/not-approved", "wrong-path POST on relay")):
            denied_http = _run(commands.http_denial_probe(method, path), operation=f"probe {label}", allowed_failure=True)
            commands.require_http_denial(denied_http.returncode, denied_http.stdout)
        observations["relay_get_denied"] = True
        observations["relay_wrong_path_post_denied"] = True
        if cancel_model_audit is not None:
            if manifest.data_class != "synthetic" or commands.model_id != "fixture-model-v1":
                raise ProbeFailure("active cancellation probe requires the synthetic fixture model")
            run_active_cancellation_probe(commands, manifest.stage_id, cancel_model_audit, observations)
            return observations
        worker = _run(commands.run_worker(manifest.stage_id), operation="run in-sandbox graph", timeout=600, allowed_failure=True)
        observations["worker_exit"] = worker.returncode
        if worker.returncode != 0:
            error_kind = safe_worker_error_kind(worker.stderr)
            observations["worker_error_kind"] = error_kind
            raise ProbeFailure(f"run in-sandbox graph failed (exit {worker.returncode}; {error_kind})")
        _run(commands.download_result(output_dir / "result.json"), operation="download graph result")
        result = json.loads((output_dir / "result.json").read_text(encoding="utf-8"))
        if result.get("stage_id") != manifest.stage_id or result.get("verified") is not True or [step.get("step") for step in result.get("steps", [])] != ["plan", "retrieve", "synthesize", "verify"]:
            raise ProbeFailure("worker result did not complete the four stages")
        tool_calls = result.get("retrieval_tool_calls")
        if not isinstance(tool_calls, list) or len(tool_calls) != len(manifest.source_ids) or {entry.get("source_id") for entry in tool_calls if isinstance(entry, dict) and entry.get("decision") == "allow"} != set(manifest.source_ids):
            raise ProbeFailure("observed read_fixture calls did not match admitted sources")
        request_count = result.get("model_requests_observed")
        if type(request_count) is not int or not 5 <= request_count <= manifest.limits.max_model_calls:
            raise ProbeFailure("actual model request count was not bounded and observed")
        observations["allowed_fixture_reads"] = [entry["source_id"] for entry in tool_calls]
        observations["actual_model_requests"] = request_count
        if audit_file is not None:
            events = _read_synthetic_model_audit(audit_file)
            expected_stages = ["plan", *["retrieve"] * (len(manifest.source_ids) + 1), "synthesize", "verify"]
            if (
                len(events) != request_count
                or [event.get("request_number") for event in events] != list(range(1, request_count + 1))
                or [event.get("stage") for event in events] != expected_stages
                or any(event.get("model_id") != commands.model_id or event.get("decision") != "allow" for event in events)
            ):
                raise ProbeFailure("synthetic model audit does not match the completed graph")
            observations["synthetic_model_audit_request_count"] = len(events)
        observations["worker_processes"] = [{key: step.get(key) for key in ("step", "pid", "hostname", "pid_namespace")} for step in result["steps"]]
        observations["live_conformance"] = "partial: process and policy inspection still require independent review"
        return observations
    except (ProbeFailure, OSError, json.JSONDecodeError) as error:
        observations["failure"] = str(error) if isinstance(error, ProbeFailure) else type(error).__name__
        raise
    finally:
        if create_attempted and not observations.get("sandbox_absent_after_delete"):
            _observe_cleanup(commands, observations)
        (output_dir / "observations.json").write_text(json.dumps(observations, indent=2, sort_keys=True), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Disposable OpenShell full-graph spike launcher")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--sandbox-name", required=True)
    parser.add_argument("--image", required=True, help="immutable worker image ref with sha256 digest")
    parser.add_argument("--relay-host", required=True)
    parser.add_argument("--relay-port", required=True, type=int)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--openshell-cli", required=True, help="absolute path to isolated v0.1.5 CLI")
    parser.add_argument("--gateway-endpoint", required=True, help="explicit disposable loopback HTTP gateway URL")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--execute", action="store_true", help="otherwise emit a dry-run command plan")
    parser.add_argument("--synthetic-model-audit", type=Path, help="fresh host-only audit path from the credential-free fixture model")
    parser.add_argument("--cancel-model-audit", type=Path, help="synthetic-only: delete during a delayed first fixture-model response")
    args = parser.parse_args(argv)
    if args.cancel_model_audit is not None and not args.execute:
        parser.error("active cancellation probe requires --execute")
    manifest = StageManifest.load(args.manifest)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    policy_file = args.output_dir / "policy.yaml"
    digest = write_policy(policy_file, args.relay_host, args.relay_port)
    commands = OpenShellCommands(args.sandbox_name, args.image, str(policy_file), f"http://{args.relay_host}:{args.relay_port}/v1", args.model_id, args.openshell_cli, args.gateway_endpoint)
    if not args.execute:
        print(json.dumps({"policy_sha256": digest, "commands": [
            commands.get(), commands.create(), commands.get(), commands.policy_full(), commands.provider_list(),
            commands.worker_import_probe(), commands.read_only_probe(), commands.upload_manifest(args.manifest),
            commands.verify_uploaded_manifest(args.manifest), commands.wrong_stage_probe(manifest.stage_id),
            commands.source_denial_probe(manifest.stage_id),
            commands.denied_egress_probe(), commands.http_denial_probe("GET", "/v1/chat/completions"),
            commands.http_denial_probe("POST", "/v1/not-approved"), commands.run_worker(manifest.stage_id),
            commands.download_result(args.output_dir / "result.json"), commands.delete(), commands.get(),
        ]}, indent=2))
        return 0
    observations = run_live(
        commands, args.manifest, args.output_dir / "observations",
        synthetic_model_audit=args.synthetic_model_audit, cancel_model_audit=args.cancel_model_audit,
    )
    print(json.dumps(observations, sort_keys=True))
    return 0 if observations.get("sandbox_absent_after_delete") else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ProbeFailure, ValueError, OSError) as error:
        print(f"launcher failed closed: {error}", file=sys.stderr)
        raise SystemExit(2)
