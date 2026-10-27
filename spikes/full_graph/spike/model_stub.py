"""Credential-free fixture model for runtime compatibility checks only.

This deterministic stub is outside the worker and speaks Chat Completions.
Its output cannot be used for research quality or spend comparison.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


class StubRejected(ValueError):
    """The fixture model was called outside its one synthetic stage."""


_SYNTHESIS = json.dumps({
    "claims": [
        {"text": "Team Atlas owns Aurora.", "source_id": "ownership", "quote": "Team Atlas owns Project Aurora."},
        {"text": "The runbook took effect on 2026-02-01.", "source_id": "runbook", "quote": "The Aurora runbook took effect on 2026-02-01."},
    ],
    "limitations": "Only the fixed synthetic sources were reviewed.",
})


class FixtureModel:
    def __init__(self, stage_id: str, model_id: str, *, max_requests: int = 8, audit_file: Path | None = None, delay_first_response_seconds: float = 0):
        if not stage_id or not model_id or not 4 <= max_requests <= 32:
            raise ValueError("invalid fixture model binding")
        if type(delay_first_response_seconds) not in (int, float) or not 0 <= delay_first_response_seconds <= 30:
            raise ValueError("invalid synthetic response delay")
        if audit_file is not None and (not audit_file.is_absolute() or audit_file.is_symlink()):
            raise ValueError("synthetic audit file must be an absolute non-symlink path")
        if audit_file is not None:
            descriptor = os.open(audit_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
            os.close(descriptor)
        self.stage_id = stage_id
        self.model_id = model_id
        self.max_requests = max_requests
        self.audit_file = audit_file
        self.delay_first_response_seconds = delay_first_response_seconds
        self.requests = 0
        self._lock = threading.Lock()

    def _audit(self, *, stage: str, tool_names: list[str], decision: str, finish_reason: str) -> None:
        if self.audit_file is None:
            return
        safe_names = [name if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", name) else "<invalid>" for name in tool_names[:16]]
        if len(tool_names) > 16:
            safe_names.append("<truncated>")
        event = {
            "request_number": self.requests + (1 if decision == "deny" else 0),
            "stage": stage,
            "model_id": self.model_id,
            "effective_tools": safe_names,
            "finish_reason": finish_reason,
            "decision": decision,
            "response_delay_seconds": self.delay_first_response_seconds if decision == "allow" and self.requests == 1 and stage == "plan" else 0,
        }
        with self.audit_file.open("a", encoding="utf-8") as audit:
            audit.write(json.dumps(event, sort_keys=True) + "\n")

    def answer(self, payload: Any, stage_id: str) -> dict[str, Any]:
        if stage_id != self.stage_id or not isinstance(payload, dict) or payload.get("model") != self.model_id:
            with self._lock:
                self._audit(stage="binding", tool_names=[], decision="deny", finish_reason="binding")
            raise StubRejected("fixture stage or model mismatch")
        messages = payload.get("messages")
        if not isinstance(messages, list) or not messages or not all(isinstance(item, dict) for item in messages):
            raise StubRejected("invalid fixture messages")
        prompt = "\n".join(str(item.get("content", "")) for item in messages if item.get("role") == "user")
        tools = payload.get("tools", [])
        if not isinstance(tools, list) or not all(isinstance(tool, dict) and tool.get("type") == "function" and isinstance(tool.get("function"), dict) and isinstance(tool["function"].get("name"), str) for tool in tools):
            raise StubRejected("invalid effective tool catalog")
        tool_names = [tool["function"]["name"] for tool in tools]
        message: dict[str, Any]
        finish_reason = "stop"
        if "Produce a bounded research plan" in prompt:
            stage = "plan"
            content = "Read ownership and runbook, then cite exact evidence quotes."
        elif "Inspect only the admitted fixed synthetic fixture sources" in prompt:
            stage = "retrieve"
            tool_results = {item.get("tool_call_id"): item.get("content") for item in messages if item.get("role") == "tool"}
            if "call_ownership" not in tool_results:
                source_id = "ownership"
            elif "call_runbook" not in tool_results:
                if "Team Atlas owns Project Aurora." not in str(tool_results["call_ownership"]):
                    raise StubRejected("ownership tool result is absent or changed")
                source_id = "runbook"
            else:
                if "The Aurora runbook took effect on 2026-02-01." not in str(tool_results["call_runbook"]):
                    raise StubRejected("runbook tool result is absent or changed")
                source_id = ""
            if source_id:
                content = ""
                finish_reason = "tool_calls"
                message = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": f"call_{source_id}",
                        "type": "function",
                        "function": {"name": "read_fixture", "arguments": json.dumps({"source_id": source_id}, separators=(",", ":"))},
                    }],
                }
            else:
                content = "The selected snapshots state Team Atlas ownership and a 2026-02-01 effective date."
        elif "Return only a JSON object with keys claims and limitations" in prompt:
            stage = "synthesize"
            content = _SYNTHESIS
        elif "Check whether every claim is supported by its exact quote" in prompt:
            stage = "verify"
            content = '{"approved": true}'
        else:
            raise StubRejected("unrecognized fixture stage prompt")
        if tool_names != (["read_fixture"] if stage == "retrieve" else []):
            with self._lock:
                self._audit(stage=stage, tool_names=tool_names, decision="deny", finish_reason="tool_catalog")
            raise StubRejected("effective tool catalog differs from the fixed stage")
        with self._lock:
            if self.requests >= self.max_requests:
                raise StubRejected("fixture model call cap reached")
            self.requests += 1
            self._audit(stage=stage, tool_names=tool_names, decision="allow", finish_reason=finish_reason)
            hold_first_plan = self.requests == 1 and stage == "plan" and self.delay_first_response_seconds > 0
        if hold_first_plan:
            time.sleep(self.delay_first_response_seconds)
        if finish_reason == "stop":
            message = {"role": "assistant", "content": content}
        return {
            "id": f"chatcmpl-spike-{self.requests}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": self.model_id,
            "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
            "usage": {"prompt_tokens": 100, "completion_tokens": min(100, len(content) // 4 + 1), "total_tokens": 200},
        }


def make_handler(model: FixtureModel):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_POST(self) -> None:
            if self.path != "/v1/chat/completions":
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 1 <= length <= 16_384:
                    raise StubRejected("request byte bound")
                payload = json.loads(self.rfile.read(length))
                answer = model.answer(payload, self.headers.get("X-Research-Stage-Id", ""))
            except (ValueError, json.JSONDecodeError) as error:
                self.send_error(403, str(error))
                return
            raw = json.dumps(answer, separators=(",", ":")).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                # An active cancellation can close the worker's socket while
                # this synthetic response is deliberately held.
                pass

    return Handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a credential-free deterministic synthetic model stub")
    parser.add_argument("--stage-id", required=True)
    parser.add_argument("--model-id", default="fixture-model-v1")
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--audit-file", type=Path, help="host-only JSONL of request counts and effective tool names; no prompts")
    parser.add_argument("--delay-first-response-seconds", type=float, default=0, help="synthetic-only plan hold for active cancellation proof")
    args = parser.parse_args(argv)
    model = FixtureModel(args.stage_id, args.model_id, audit_file=args.audit_file, delay_first_response_seconds=args.delay_first_response_seconds)
    server = ThreadingHTTPServer((args.bind, args.port), make_handler(model))
    print(json.dumps({"fixture_model_listening": True, "port": args.port, "stage_id": args.stage_id}), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
