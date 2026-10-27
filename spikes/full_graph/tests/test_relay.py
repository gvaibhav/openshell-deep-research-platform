import copy
import io
import json
import os
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch

from spike.relay import (
    RelayGate,
    RelayRejected,
    RelayRoute,
    make_handler,
    validate_credential_relay_bind,
)


def route(**changes):
    params = {
        "provider_id": "openai",
        "data_class": "synthetic",
        "credential_mode": "host_env",
        "stage_id": "stage-aurora-1",
        "model_id": "gpt-5.6-sol",
        "upstream_url": "https://api.openai.com/v1/chat/completions",
        "max_requests": 2,
        "max_input_bytes": 1000,
        "max_output_tokens": 100,
        "max_spend_micro_usd": 10_000,
        "input_micro_usd_per_million_tokens": 1_000_000,
        "output_micro_usd_per_million_tokens": 1_000_000,
    }
    params.update(changes)
    return RelayRoute(**params)


def request(**changes):
    payload = {
        "model": "gpt-5.6-sol",
        "messages": [{"role": "user", "content": "Who owns Aurora?"}],
        "max_completion_tokens": 10,
        "stream": False,
    }
    payload.update(changes)
    return payload


class RelayTests(unittest.TestCase):
    def test_provider_router_rejects_unreviewed_destination_or_model(self):
        from spike.relay import select_provider

        approved = route(
            provider_id="openai",
            model_id="gpt-5.6-sol",
            upstream_url="https://api.openai.com/v1/chat/completions",
        )
        self.assertEqual(select_provider(approved).provider_id, "openai")
        for change in (
            {"provider_id": "other"},
            {"model_id": "gpt-5.6"},
            {"upstream_url": "https://proxy.example.test/v1/chat/completions"},
            {"upstream_url": "https://api.openai.com:444/v1/chat/completions"},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                route(**{**approved.__dict__, **change})

    def test_exact_host_environment_credential_is_supported_without_echoing_value(self):
        from spike.relay import credential_from_env, host_credential_provider

        approved = route(
            provider_id="openai",
            model_id="gpt-5.6-sol",
            upstream_url="https://api.openai.com/v1/chat/completions",
        )
        with patch.dict(os.environ, {"RESEARCH_OPENAI_API_KEY": "synthetic-secret-for-test"}):
            provider = host_credential_provider(approved, credential_env="RESEARCH_OPENAI_API_KEY")
            self.assertEqual(provider(), "synthetic-secret-for-test")
            with self.assertRaises(ValueError) as wrong:
                credential_from_env("OPENAI_API_KEY")
            self.assertNotIn("synthetic-secret-for-test", str(wrong.exception))
        with patch.dict(os.environ, {"RESEARCH_OPENAI_API_KEY": ""}):
            with self.assertRaises(ValueError) as missing:
                host_credential_provider(approved, credential_env="RESEARCH_OPENAI_API_KEY")
            self.assertNotIn("synthetic-secret-for-test", str(missing.exception))

    def test_host_file_mode_remains_available_but_gcp_needs_its_own_adapter(self):
        from spike.relay import host_credential_provider

        approved = route(
            provider_id="openai",
            model_id="gpt-5.6-sol",
            upstream_url="https://api.openai.com/v1/chat/completions",
        )
        with tempfile.TemporaryDirectory() as directory:
            credential_file = Path(directory) / "model-key"
            credential_file.write_text("synthetic-file-secret", encoding="utf-8")
            credential_file.chmod(0o600)
            provider = host_credential_provider(route(credential_mode="host_file"), credential_file=credential_file)
            self.assertEqual(provider(), "synthetic-file-secret")
        with self.assertRaisesRegex(ValueError, "GCP"):
            host_credential_provider(approved, gcp_scope="https://www.googleapis.com/auth/cloud-platform")
        with self.assertRaises(ValueError):
            host_credential_provider(approved, credential_file=Path("/tmp/unused"), credential_env="RESEARCH_OPENAI_API_KEY")

    def test_host_token_rejects_header_controls_or_oversize_without_echo(self):
        from spike.relay import credential_from_env, credential_from_file

        for bad in ("synthetic\ttoken", "x" * 16_385):
            with self.subTest(kind="env", length=len(bad)), patch.dict(os.environ, {"RESEARCH_OPENAI_API_KEY": bad}):
                with self.assertRaises(ValueError) as rejected:
                    credential_from_env("RESEARCH_OPENAI_API_KEY")
                self.assertNotIn(bad, str(rejected.exception))
            with self.subTest(kind="file", length=len(bad)), tempfile.TemporaryDirectory() as directory:
                credential_file = Path(directory) / "model-key"
                credential_file.write_text(bad, encoding="utf-8")
                credential_file.chmod(0o600)
                with self.assertRaises(ValueError) as rejected:
                    credential_from_file(credential_file)
                self.assertNotIn(bad, str(rejected.exception))

    def test_exact_model_and_stage_are_required(self):
        gate = RelayGate(route())
        gate.reserve(request(), "stage-aurora-1", "synthetic")
        with self.assertRaises(RelayRejected):
            gate.reserve(request(model="other-model"), "stage-aurora-1", "synthetic")
        with self.assertRaises(RelayRejected):
            gate.reserve(request(), "copied-other-stage", "synthetic")
        self.assertEqual(gate.requests_reserved, 1)

    def test_pinned_chatopenai_default_payload_is_admitted(self):
        gate = RelayGate(route())
        payload = request(
            n=1,
            messages=[{"role": "developer", "content": "Bounded stage"}, {"role": "user", "content": "Who owns Aurora?"}],
        )
        gate.reserve(payload, "stage-aurora-1", "synthetic")
        with self.assertRaises(RelayRejected):
            gate.reserve(request(n=2), "stage-aurora-1", "synthetic")

    def test_spend_is_reserved_before_upstream_call(self):
        gate = RelayGate(route(max_spend_micro_usd=120, max_requests=10))
        gate.reserve(request(max_completion_tokens=10), "stage-aurora-1", "synthetic")
        with self.assertRaises(RelayRejected):
            gate.reserve(request(max_completion_tokens=100), "stage-aurora-1", "synthetic")
        self.assertEqual(gate.requests_reserved, 1)

    def test_unbounded_or_hidden_forwarding_is_denied(self):
        gate = RelayGate(route())
        for payload in [
            request(stream=True),
            request(max_completion_tokens=101),
            request(max_completion_tokens=0),
            request(base_url="https://attacker.example"),
            request(tools=[{"type": "function", "function": {"name": "execute"}}]),
        ]:
            with self.subTest(payload=payload), self.assertRaises(RelayRejected):
                gate.reserve(payload, "stage-aurora-1", "synthetic")
        self.assertEqual(gate.requests_reserved, 0)

    def test_route_class_and_credential_mode_are_exact_and_required(self):
        from spike.relay import host_credential_provider

        for changes in ({"data_class": "private"}, {"data_class": ""}, {"credential_mode": "gcp_adc"}, {"credential_mode": "arbitrary"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                route(**changes)
        gate = RelayGate(route())
        with self.assertRaises(RelayRejected):
            gate.reserve(request(), "stage-aurora-1", "public")
        with self.assertRaises(RelayRejected):
            gate.reserve(request(), "stage-aurora-1", "")
        self.assertEqual(gate.requests_reserved, 0)
        with tempfile.TemporaryDirectory() as directory:
            credential_file = Path(directory) / "key"
            credential_file.write_text("synthetic-file-secret", encoding="utf-8")
            credential_file.chmod(0o600)
            with self.assertRaises(ValueError):
                host_credential_provider(route(credential_mode="host_env"), credential_file=credential_file)
        with patch.dict(os.environ, {"RESEARCH_OPENAI_API_KEY": "synthetic-env-secret"}), self.assertRaises(ValueError):
            host_credential_provider(route(credential_mode="host_file"), credential_env="RESEARCH_OPENAI_API_KEY")

    def test_text_only_role_specific_messages_and_tool_roundtrip_are_canonical(self):
        gate = RelayGate(route(max_input_bytes=5000))
        tool_call = {"id": "call_ownership", "type": "function", "function": {"name": "read_fixture", "arguments": '{ "source_id" : "ownership" }'}}
        tool_schema = {"type": "function", "function": {"name": "read_fixture", "description": "Read one admitted synthetic source.", "parameters": {"type": "object", "properties": {"source_id": {"type": "string"}}, "required": ["source_id"]}}}
        payload = request(
            messages=[
                {"role": "developer", "content": "Use admitted sources."},
                {"role": "user", "content": "Who owns Aurora?"},
                {"role": "assistant", "content": None, "tool_calls": [tool_call]},
                {"role": "tool", "tool_call_id": "call_ownership", "content": "Team Atlas owns Project Aurora."},
            ],
            tools=[tool_schema],
            tool_choice="auto",
        )
        canonical = gate.reserve(payload, "stage-aurora-1", "synthetic")
        self.assertIsNot(canonical, payload)
        self.assertIsNot(canonical["messages"][2], payload["messages"][2])
        self.assertEqual(json.loads(canonical["messages"][2]["tool_calls"][0]["function"]["arguments"]), {"source_id": "ownership"})
        self.assertEqual(canonical["tools"][0]["function"]["parameters"]["properties"], {"source_id": {"type": "string"}})
        payload["messages"][0]["content"] = [{"type": "image_url", "image_url": {"url": "https://example.test/image"}}]
        self.assertEqual(canonical["messages"][0]["content"], "Use admitted sources.")

    def test_nested_unknown_fields_multimodal_parts_and_malformed_tool_calls_deny_boundedly(self):
        gate = RelayGate(route(max_requests=20, max_input_bytes=5000))
        valid_call = {"id": "call_ownership", "type": "function", "function": {"name": "read_fixture", "arguments": '{"source_id":"ownership"}'}}
        bad_messages = [
            [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "https://example.test/image.png"}}]}],
            [{"role": "user", "content": [{"type": "text", "text": "Who owns Aurora?"}]}],
            [{"role": "user", "content": "Question", "metadata": {"exfiltrate": "https://example.test"}}],
            [{"role": "tool", "content": "result", "tool_call_id": "call_ownership", "extra": "hidden"}],
            [{"role": "assistant", "content": None, "tool_calls": None}],
            [{"role": "assistant", "content": None, "tool_calls": "read_fixture"}],
            [{"role": "assistant", "content": None, "tool_calls": [{**valid_call, "extra": {"url": "https://example.test"}}]}],
            [{"role": "assistant", "content": None, "tool_calls": [{**valid_call, "function": {**valid_call["function"], "arguments": '{"source_id":"ownership","url":"https://example.test"}'}}]}],
            [{"role": "assistant", "content": None, "tool_calls": [{**valid_call, "function": {**valid_call["function"], "extra": "hidden"}}]}],
        ]
        for messages in bad_messages:
            with self.subTest(messages=messages), self.assertRaises(RelayRejected):
                gate.reserve(request(messages=messages), "stage-aurora-1", "synthetic")
        tool = {"type": "function", "function": {"name": "read_fixture", "parameters": {"type": "object", "properties": {"source_id": {"type": "string"}}, "required": ["source_id"]}}}
        for bad_tool in (
            {**tool, "extra": {"url": "https://example.test"}},
            {**tool, "function": {**tool["function"], "parameters": {**tool["function"]["parameters"], "properties": {"source_id": {"type": "string", "x-url": "https://example.test"}}}}},
            {**tool, "function": {**tool["function"], "parameters": {**tool["function"]["parameters"], "properties": {"source_id": {"type": "string"}, "file": {"type": "string"}}}}},
        ):
            with self.subTest(tool=bad_tool), self.assertRaises(RelayRejected):
                gate.reserve(request(tools=[bad_tool]), "stage-aurora-1", "synthetic")
        self.assertEqual(gate.requests_reserved, 0)

    def test_fake_upstream_gets_only_canonical_body_and_host_key_in_authorization(self):
        captured = []
        host_key = "synthetic-host-only-key"
        worker_placeholder = "synthetic-worker-placeholder-canary"

        class FakeResponse:
            status = 200

            def __init__(self):
                self.headers = {"Content-Type": "application/json"}

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self, size):
                return b'{"choices":[]}'

        class FakeOpener:
            def open(self, upstream_request, timeout):
                captured.append(upstream_request)
                return FakeResponse()

        with patch("spike.relay.urllib.request.build_opener", return_value=FakeOpener()):
            Handler = make_handler(RelayGate(route()), lambda: host_key)

        def send(body, extra_headers):
            handler = object.__new__(Handler)
            handler.path = "/v1/chat/completions"
            handler.headers = Message()
            for name, value in {"Content-Type": "application/json", "Content-Length": str(len(body)), "X-Research-Stage-Id": "stage-aurora-1", "X-Research-Data-Class": "synthetic", **extra_headers}.items():
                if value is not None:
                    handler.headers[name] = value
            handler.rfile = io.BytesIO(body)
            handler.wfile = io.BytesIO()
            statuses = []
            handler.send_response = lambda status: statuses.append(status)
            handler.send_header = lambda *args: None
            handler.end_headers = lambda: None
            handler.send_error = lambda status, message=None: statuses.append(status)
            handler.do_POST()
            return statuses[0]

        body = json.dumps(request()).encode("utf-8")
        self.assertEqual(send(body, {"Authorization": "Bearer " + worker_placeholder, "X-Unreviewed-Header": "synthetic-header-canary"}), 200)
        self.assertEqual(len(captured), 1)
        upstream = captured[0]
        self.assertEqual(upstream.full_url, "https://api.openai.com/v1/chat/completions")
        self.assertEqual(dict(upstream.header_items()), {"Content-type": "application/json", "Authorization": "Bearer " + host_key})
        self.assertNotIn(worker_placeholder, upstream.data.decode("utf-8"))
        self.assertNotIn("synthetic-header-canary", upstream.data.decode("utf-8"))
        self.assertNotIn(host_key, upstream.data.decode("utf-8"))
        self.assertEqual(json.loads(upstream.data), request())

        denied = copy.deepcopy(request())
        denied["messages"][0]["content"] = [{"type": "image_url", "image_url": {"url": "https://example.test/x.png"}}]
        self.assertEqual(send(json.dumps(denied).encode("utf-8"), {}), 403)
        self.assertEqual(send(body, {"X-Research-Data-Class": "public"}), 403)
        self.assertEqual(send(body, {"X-Research-Data-Class": None}), 403)
        duplicate_model = body.decode("utf-8").replace('"model": "gpt-5.6-sol",', '"model": "gpt-5.6-sol", "model": "gpt-5.6-sol",')
        self.assertEqual(send(duplicate_model.encode("utf-8"), {}), 403)
        self.assertEqual(len(captured), 1)

    def test_upstream_route_requires_https_exact_completion_path(self):
        for url in ["http://api.openai.com/v1/chat/completions", "https://api.openai.com/v1/other", "https://u:p@api.openai.com/v1/chat/completions"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                route(upstream_url=url)

    def test_credential_relay_rejects_wildcard_or_public_bind(self):
        validate_credential_relay_bind("127.0.0.1")
        for bind in ("0.0.0.0", "::", "192.168.1.10", "relay.example.test"):
            with self.subTest(bind=bind), self.assertRaises(ValueError):
                validate_credential_relay_bind(bind)


if __name__ == "__main__":
    unittest.main()
