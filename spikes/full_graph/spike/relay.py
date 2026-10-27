"""Disposable host-side OpenAI-compatible relay with exact route and spend reservation.

Only this host process opens the upstream credential reference. The worker
sends a nonsecret placeholder to satisfy the OpenAI client constructor; its
Authorization header is discarded and never forwarded upstream.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import stat
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


class RelayRejected(ValueError):
    """The relay rejected an unapproved or over-budget request."""


@dataclass(frozen=True)
class ProviderSpec:
    """One explicitly reviewed upstream route and its host credential mode."""

    provider_id: str
    model_id: str
    upstream_url: str
    credential_env: str
    data_classes: frozenset[str]
    credential_modes: frozenset[str]


_PROVIDER_SPECS = {
    "openai": ProviderSpec(
        provider_id="openai",
        model_id="gpt-5.6-sol",
        upstream_url="https://api.openai.com/v1/chat/completions",
        credential_env="RESEARCH_OPENAI_API_KEY",
        data_classes=frozenset({"synthetic", "public"}),
        credential_modes=frozenset({"host_env", "host_file"}),
    ),
}


def select_provider(route: RelayRoute) -> ProviderSpec:
    """Reject a model/provider/destination combination absent from the review set."""
    if not isinstance(route.provider_id, str):
        raise TypeError("unsupported model provider")
    provider = _PROVIDER_SPECS.get(route.provider_id)
    if provider is None:
        raise ValueError("unsupported model provider")
    if route.model_id != provider.model_id or route.upstream_url != provider.upstream_url:
        raise ValueError("model route differs from the reviewed provider route")
    if route.data_class not in provider.data_classes or route.credential_mode not in provider.credential_modes:
        raise ValueError("model data class or credential mode is not reviewed")
    return provider


def validate_credential_relay_bind(bind: str) -> None:
    """Keep credential-bearing prototype ingress local until separately qualified."""
    try:
        address = ipaddress.ip_address(bind)
    except ValueError as error:
        raise ValueError("credential relay bind must be a loopback IP") from error
    if not address.is_loopback:
        raise ValueError("credential relay bind must be loopback; sandbox ingress is unqualified")


def _positive_int(value: Any, name: str, maximum: int) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f"{name} must be in [1, {maximum}]")
    return value


@dataclass(frozen=True)
class RelayRoute:
    provider_id: str
    data_class: str
    credential_mode: str
    stage_id: str
    model_id: str
    upstream_url: str
    max_requests: int
    max_input_bytes: int
    max_output_tokens: int
    max_spend_micro_usd: int
    input_micro_usd_per_million_tokens: int
    output_micro_usd_per_million_tokens: int

    def __post_init__(self) -> None:
        if not all(isinstance(value, str) for value in (self.provider_id, self.data_class, self.credential_mode, self.stage_id, self.model_id, self.upstream_url)):
            raise ValueError("model route has invalid field types")
        url = urlparse(self.upstream_url)
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment or url.path != "/v1/chat/completions":
            raise ValueError("upstream URL must be an exact HTTPS /v1/chat/completions route")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,79}", self.stage_id) or not self.model_id or len(self.model_id) > 128:
            raise ValueError("invalid stage or model ID")
        select_provider(self)
        for name, maximum in (
            ("max_requests", 100), ("max_input_bytes", 65536), ("max_output_tokens", 4096),
            ("max_spend_micro_usd", 1_000_000_000),
            ("input_micro_usd_per_million_tokens", 1_000_000_000),
            ("output_micro_usd_per_million_tokens", 1_000_000_000),
        ):
            _positive_int(getattr(self, name), name, maximum)


def _object(value: Any, required: set[str], optional: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise RelayRejected(f"invalid {label} object")
    if not required.issubset(value) or set(value) - required - optional:
        raise RelayRejected(f"unsupported {label} field")
    return value


def _text(value: Any, maximum: int, label: str, *, nonempty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > maximum or (nonempty and not value):
        raise RelayRejected(f"invalid {label}")
    return value


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RelayRejected("duplicate JSON field")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise RelayRejected("non-finite JSON value")


def _strict_json(raw: str | bytes) -> Any:
    try:
        return json.loads(raw, object_pairs_hook=_unique_pairs, parse_constant=_reject_constant)
    except (json.JSONDecodeError, UnicodeError, RecursionError) as error:
        raise RelayRejected("invalid bounded JSON") from error


def _call_id(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise RelayRejected("invalid tool call ID")
    return value


def _canonical_tool_call(value: Any) -> dict[str, Any]:
    call = _object(value, {"id", "type", "function"}, set(), "tool call")
    function = _object(call["function"], {"name", "arguments"}, set(), "tool function")
    if call["type"] != "function" or function["name"] != "read_fixture":
        raise RelayRejected("unapproved tool call in history")
    arguments = _strict_json(_text(function["arguments"], 512, "tool arguments", nonempty=True))
    argument_object = _object(arguments, {"source_id"}, set(), "tool arguments")
    source_id = _text(argument_object["source_id"], 80, "source ID", nonempty=True)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", source_id):
        raise RelayRejected("invalid source ID")
    return {
        "id": _call_id(call["id"]),
        "type": "function",
        "function": {"name": "read_fixture", "arguments": json.dumps({"source_id": source_id}, separators=(",", ":"))},
    }


def _canonical_messages(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not 1 <= len(value) <= 32:
        raise RelayRejected("invalid message count")
    result: list[dict[str, Any]] = []
    pending_calls: set[str] = set()
    saw_user = False
    for item in value:
        message = _object(item, {"role", "content"}, {"tool_calls", "tool_call_id"}, "message")
        role = message["role"]
        if not isinstance(role, str):
            raise RelayRejected("invalid message role")
        if role in {"system", "developer", "user"}:
            _object(message, {"role", "content"}, set(), "message role")
            if pending_calls:
                raise RelayRejected("tool result is missing before next message")
            content = _text(message["content"], 16_384, "text message")
            result.append({"role": role, "content": content})
            saw_user = saw_user or role == "user"
        elif role == "assistant":
            _object(message, {"role", "content"}, {"tool_calls"}, "assistant message")
            if pending_calls:
                raise RelayRejected("tool result is missing before next assistant message")
            calls: list[dict[str, Any]] = []
            if "tool_calls" in message:
                raw_calls = message["tool_calls"]
                if not isinstance(raw_calls, list) or len(raw_calls) != 1:
                    raise RelayRejected("invalid bounded tool calls")
                calls = [_canonical_tool_call(raw_calls[0])]
            content = message["content"]
            if content is None and not calls:
                raise RelayRejected("assistant text is missing")
            if content is not None:
                content = _text(content, 16_384, "assistant text")
            canonical: dict[str, Any] = {"role": "assistant", "content": content}
            if calls:
                canonical["tool_calls"] = calls
                pending_calls = {call["id"] for call in calls}
            result.append(canonical)
        elif role == "tool":
            _object(message, {"role", "tool_call_id", "content"}, set(), "tool message")
            call_id = _call_id(message["tool_call_id"])
            if call_id not in pending_calls:
                raise RelayRejected("tool result has no approved call")
            pending_calls.remove(call_id)
            result.append({"role": "tool", "tool_call_id": call_id, "content": _text(message["content"], 16_384, "tool text")})
        else:
            raise RelayRejected("invalid message role")
    if pending_calls or not saw_user:
        raise RelayRejected("message history is incomplete")
    return result


def _canonical_tool(value: Any) -> dict[str, Any]:
    tool = _object(value, {"type", "function"}, set(), "tool schema")
    function = _object(tool["function"], {"name", "parameters"}, {"description", "strict"}, "tool function schema")
    if tool["type"] != "function" or function["name"] != "read_fixture":
        raise RelayRejected("unapproved tool schema")
    parameters = _object(function["parameters"], {"type", "properties", "required"}, {"title", "description", "additionalProperties"}, "tool parameters")
    if parameters["type"] != "object" or parameters["required"] != ["source_id"]:
        raise RelayRejected("unapproved tool parameter schema")
    properties = _object(parameters["properties"], {"source_id"}, set(), "tool properties")
    source = _object(properties["source_id"], {"type"}, {"title", "description"}, "source ID schema")
    if source["type"] != "string" or parameters.get("additionalProperties", False) is not False:
        raise RelayRejected("unapproved source ID schema")
    canonical_source = {"type": "string"}
    for name in ("title", "description"):
        if name in source:
            canonical_source[name] = _text(source[name], 256, f"source {name}")
    canonical_parameters: dict[str, Any] = {"type": "object", "properties": {"source_id": canonical_source}, "required": ["source_id"]}
    for name in ("title", "description"):
        if name in parameters:
            canonical_parameters[name] = _text(parameters[name], 256, f"parameters {name}")
    if "additionalProperties" in parameters:
        canonical_parameters["additionalProperties"] = False
    canonical_function: dict[str, Any] = {"name": "read_fixture", "parameters": canonical_parameters}
    if "description" in function:
        canonical_function["description"] = _text(function["description"], 512, "tool description")
    if "strict" in function:
        if type(function["strict"]) is not bool or (function["strict"] and "additionalProperties" not in parameters):
            raise RelayRejected("unsupported strict tool schema")
        canonical_function["strict"] = function["strict"]
    return {"type": "function", "function": canonical_function}


@dataclass
class RelayGate:
    route: RelayRoute
    requests_reserved: int = 0
    spend_reserved_micro_usd: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def reserve(self, payload: Any, stage_id: str, data_class: str) -> dict[str, Any]:
        route = self.route
        if stage_id != route.stage_id:
            raise RelayRejected("stage binding mismatch")
        if data_class != route.data_class:
            raise RelayRejected("stage data class differs from the reviewed route")
        if not isinstance(payload, dict):
            raise RelayRejected("request must be an object")
        allowed = {"model", "messages", "max_tokens", "max_completion_tokens", "stream", "temperature", "tools", "tool_choice", "parallel_tool_calls", "n"}
        if not all(isinstance(key, str) for key in payload) or set(payload) - allowed:
            raise RelayRejected("unsupported request parameter")
        if payload.get("model") != route.model_id:
            raise RelayRejected("model is outside the exact approved route")
        if payload.get("stream", False) is not False:
            raise RelayRejected("streaming is disabled for this bounded relay")
        if payload.get("n", 1) != 1 or type(payload.get("n", 1)) is not int:
            raise RelayRejected("only one completion is allowed")
        if "max_tokens" in payload and "max_completion_tokens" in payload:
            raise RelayRejected("ambiguous output token bound")
        max_output = payload.get("max_completion_tokens", payload.get("max_tokens"))
        if type(max_output) is not int or not 1 <= max_output <= route.max_output_tokens:
            raise RelayRejected("output token bound is missing or too high")
        if payload.get("parallel_tool_calls", False) is not False:
            raise RelayRejected("parallel tool calls are disabled")
        if "temperature" in payload and (type(payload["temperature"]) not in (int, float) or not 0 <= payload["temperature"] <= 1):
            raise RelayRejected("temperature is outside the bounded range")
        messages = _canonical_messages(payload.get("messages"))
        raw_tools = payload.get("tools", [])
        if not isinstance(raw_tools, list) or len(raw_tools) > 1:
            raise RelayRejected("too many tools")
        tools = [_canonical_tool(tool) for tool in raw_tools]
        if payload.get("tool_choice") not in (None, "auto", "none", "required"):
            raise RelayRejected("unsupported tool choice")
        if payload.get("tool_choice") == "required" and not tools:
            raise RelayRejected("required tool choice has no reviewed tool")
        canonical: dict[str, Any] = {"model": route.model_id, "messages": messages}
        canonical["max_completion_tokens" if "max_completion_tokens" in payload else "max_tokens"] = max_output
        if "stream" in payload:
            canonical["stream"] = False
        if "temperature" in payload:
            canonical["temperature"] = payload["temperature"]
        if "tools" in payload:
            canonical["tools"] = tools
        if "tool_choice" in payload and payload["tool_choice"] is not None:
            canonical["tool_choice"] = payload["tool_choice"]
        if "parallel_tool_calls" in payload:
            canonical["parallel_tool_calls"] = False
        if "n" in payload:
            canonical["n"] = 1
        try:
            encoded = json.dumps(canonical, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
            model_input = json.dumps({"messages": messages, "tools": tools}, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        except (TypeError, ValueError, UnicodeError) as error:
            raise RelayRejected("request is not JSON serializable") from error
        if len(encoded) > route.max_input_bytes:
            raise RelayRejected("request body exceeds byte bound")
        # UTF-8 bytes plus per-message framing is a deliberately conservative
        # local reservation. Actual provider billing must still be inspected.
        input_upper_bound = len(model_input) + 32 * len(messages)
        reserved = (
            (input_upper_bound * route.input_micro_usd_per_million_tokens + 999_999) // 1_000_000
            + (max_output * route.output_micro_usd_per_million_tokens + 999_999) // 1_000_000
        )
        with self._lock:
            if self.requests_reserved >= route.max_requests or self.spend_reserved_micro_usd + reserved > route.max_spend_micro_usd:
                raise RelayRejected("model request or spend reservation cap reached")
            self.requests_reserved += 1
            self.spend_reserved_micro_usd += reserved
        return canonical


def credential_from_file(path: Path) -> str:
    """Resolve the operator-approved reference on the host, never in worker code."""
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("credential reference must be an absolute, non-symlink file")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_size > 16384:
        raise ValueError("credential reference has unsafe ownership, mode, or size")
    value = path.read_text(encoding="utf-8").strip()
    if not _safe_bearer_value(value):
        raise ValueError("credential reference has invalid content")
    return value


def _safe_bearer_value(value: str) -> bool:
    return bool(value) and len(value) <= 16_384 and value.isascii() and all(0x21 <= ord(char) <= 0x7e for char in value)


def credential_from_env(name: str) -> str:
    """Read one named host environment variable without printing its value."""
    if name != "RESEARCH_OPENAI_API_KEY":
        raise ValueError("unsupported host credential environment name")
    value = os.environ.get(name, "")
    if not _safe_bearer_value(value):
        raise ValueError("host OpenAI credential environment is missing or invalid")
    return value


def host_credential_provider(
    route: RelayRoute,
    *,
    credential_file: Path | None = None,
    credential_env: str | None = None,
    gcp_scope: str | None = None,
) -> Callable[[], str]:
    """Select a host-only secret source for the reviewed provider adapter."""
    provider = select_provider(route)
    if sum(value is not None for value in (credential_file, credential_env, gcp_scope)) != 1:
        raise ValueError("select exactly one host credential source")
    if gcp_scope is not None:
        # The helper remains available for a future reviewed GCP endpoint. An
        # ADC token cannot be sent to this OpenAI route.
        raise ValueError("GCP workload identity requires a reviewed GCP provider adapter")
    if credential_env is not None:
        if route.credential_mode != "host_env" or credential_env != provider.credential_env:
            raise ValueError("unsupported host credential environment name")
        credential_from_env(credential_env)
        return lambda: credential_from_env(credential_env)
    assert credential_file is not None
    if route.credential_mode != "host_file":
        raise ValueError("credential file differs from reviewed route mode")
    credential_from_file(credential_file)
    return lambda: credential_from_file(credential_file)


def gcp_workload_identity_token(scope: str) -> str:
    """Obtain a short-lived GCP ADC token on the relay host for an approved scope."""
    if not scope.startswith("https://www.googleapis.com/auth/") or len(scope) > 160:
        raise ValueError("invalid approved GCP scope")
    import google.auth
    from google.auth.transport.requests import Request

    credentials, _ = google.auth.default(scopes=[scope])
    credentials.refresh(Request())
    if not credentials.token:
        raise RuntimeError("GCP workload identity returned no token")
    return credentials.token


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        # An upstream redirect must never carry a host-held credential to a
        # second destination, even if a client library would normally follow it.
        return None


def make_handler(gate: RelayGate, credential_provider: Callable[[], str]):
    upstream_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            # Do not put prompts, headers, upstream errors, or tokens in logs.
            return

        def do_POST(self) -> None:
            if self.path != "/v1/chat/completions":
                self.send_error(404)
                return
            try:
                if self.headers.get("Transfer-Encoding") or self.headers.get("Content-Type", "").split(";", 1)[0].lower() != "application/json":
                    raise RelayRejected("unsupported request framing")
                if len(self.headers.get_all("X-Research-Stage-Id", [])) != 1 or len(self.headers.get_all("X-Research-Data-Class", [])) != 1:
                    raise RelayRejected("stage route headers are missing or ambiguous")
                length = int(self.headers.get("Content-Length", "0"))
                if not 1 <= length <= gate.route.max_input_bytes:
                    raise RelayRejected("request byte bound")
                payload = _strict_json(self.rfile.read(length))
                stage_id = self.headers.get("X-Research-Stage-Id", "")
                data_class = self.headers.get("X-Research-Data-Class", "")
                validated = gate.reserve(payload, stage_id, data_class)
            except (ValueError, TypeError, UnicodeError, RecursionError):
                self.send_error(403, "request rejected")
                return
            try:
                credential = credential_provider()
                request = urllib.request.Request(
                    gate.route.upstream_url,
                    data=json.dumps(validated, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8"),
                    headers={"Content-Type": "application/json", "Authorization": "Bearer " + credential},
                    method="POST",
                )
                with upstream_opener.open(request, timeout=60) as upstream:
                    body = upstream.read(1_048_577)
                    if len(body) > 1_048_576:
                        raise RuntimeError("upstream response byte bound exceeded")
                    status = upstream.status
                    content_type = upstream.headers.get("Content-Type", "application/json")
                if status != 200 or not content_type.startswith("application/json"):
                    raise RuntimeError("upstream returned unsupported response")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (OSError, RuntimeError, ValueError, urllib.error.URLError):
                self.send_error(502, "approved model route failed")

    return Handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a disposable host-side exact-model relay")
    parser.add_argument("--route", required=True, type=Path, help="reviewed route JSON, never copied into the worker")
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--credential-file", type=Path)
    parser.add_argument("--credential-env", help="host-only RESEARCH_OPENAI_API_KEY")
    parser.add_argument("--gcp-scope")
    args = parser.parse_args(argv)
    try:
        validate_credential_relay_bind(args.bind)
        route_data = _strict_json(args.route.read_bytes())
        if not isinstance(route_data, dict):
            raise TypeError("relay route must be a JSON object")
        route = RelayRoute(**route_data)
        provider = host_credential_provider(
            route,
            credential_file=args.credential_file,
            credential_env=args.credential_env,
            gcp_scope=args.gcp_scope,
        )
    except (ValueError, TypeError, OSError) as error:
        parser.error(str(error))
    server = ThreadingHTTPServer((args.bind, args.port), make_handler(RelayGate(route), provider))
    print(json.dumps({"relay_listening": True, "bind": args.bind, "port": args.port, "provider_id": route.provider_id, "model_id": route.model_id, "stage_id": route.stage_id}), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
