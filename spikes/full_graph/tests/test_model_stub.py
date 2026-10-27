import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from spike.model_stub import FixtureModel, StubRejected


class FixtureModelTests(unittest.TestCase):
    def test_retrieval_requires_two_real_tool_responses(self):
        model = FixtureModel("stage-aurora-1", "fixture-model-v1", max_requests=8)
        prompt = "Inspect only the admitted fixed synthetic fixture sources. Admitted source IDs: ownership, runbook"
        messages = [{"role": "user", "content": prompt}]
        payload = {"model": "fixture-model-v1", "messages": messages, "tools": [{"type": "function", "function": {"name": "read_fixture"}}]}
        first = model.answer(payload, "stage-aurora-1")["choices"][0]["message"]
        self.assertEqual(first["tool_calls"][0]["function"], {"name": "read_fixture", "arguments": '{"source_id":"ownership"}'})
        messages.extend([first, {"role": "tool", "tool_call_id": "call_ownership", "content": "Team Atlas owns Project Aurora."}])
        second = model.answer({**payload, "messages": messages}, "stage-aurora-1")["choices"][0]["message"]
        self.assertEqual(second["tool_calls"][0]["function"], {"name": "read_fixture", "arguments": '{"source_id":"runbook"}'})
        messages.extend([second, {"role": "tool", "tool_call_id": "call_runbook", "content": "The Aurora runbook took effect on 2026-02-01."}])
        final = model.answer({**payload, "messages": messages}, "stage-aurora-1")["choices"][0]["message"]
        self.assertIn("Team Atlas", final["content"])
        self.assertEqual(model.requests, 3)

    def test_fixed_four_stage_responses_for_synthetic_graph(self):
        model = FixtureModel("stage-aurora-1", "fixture-model-v1", max_requests=4)
        prompts = [
            "Produce a bounded research plan for this question",
            "Inspect only the admitted fixed synthetic fixture sources",
            "Return only a JSON object with keys claims and limitations",
            "Check whether every claim is supported by its exact quote",
        ]
        outputs = []
        for prompt in prompts:
            payload = {"model": "fixture-model-v1", "messages": [{"role": "user", "content": prompt}]}
            if prompt.startswith("Inspect only"):
                payload["tools"] = [{"type": "function", "function": {"name": "read_fixture"}}]
            outputs.append(model.answer(payload, "stage-aurora-1"))
        self.assertIn("Read", outputs[0]["choices"][0]["message"]["content"])
        self.assertIn("Team Atlas", outputs[2]["choices"][0]["message"]["content"])
        self.assertIn('"approved": true', outputs[3]["choices"][0]["message"]["content"])
        with self.assertRaises(StubRejected):
            model.answer({"model": "fixture-model-v1", "messages": [{"role": "user", "content": prompts[0]}]}, "stage-aurora-1")

    def test_wrong_stage_and_model_fail_without_call(self):
        model = FixtureModel("stage-aurora-1", "fixture-model-v1", max_requests=4)
        body = {"model": "fixture-model-v1", "messages": [{"role": "user", "content": "Produce a bounded research plan"}]}
        with self.assertRaises(StubRejected):
            model.answer(body, "different-stage")
        with self.assertRaises(StubRejected):
            model.answer({**body, "model": "another-model"}, "stage-aurora-1")
        self.assertEqual(model.requests, 0)

    def test_host_audit_counts_rejected_binding_attempts_without_prompt_or_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            audit = Path(directory) / "model-audit.jsonl"
            model = FixtureModel("stage-aurora-1", "fixture-model-v1", audit_file=audit)
            body = {"model": "fixture-model-v1", "messages": [{"role": "user", "content": "synthetic-private-canary"}]}
            with self.assertRaises(StubRejected):
                model.answer(body, "wrong-stage")
            events = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(model.requests, 0)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["decision"], "deny")
        self.assertEqual(events[0]["finish_reason"], "binding")
        self.assertNotIn("wrong-stage", json.dumps(events))
        self.assertNotIn("synthetic-private-canary", json.dumps(events))

    def test_effective_tool_catalog_rejects_non_retrieval_or_extra_tool(self):
        model = FixtureModel("stage-aurora-1", "fixture-model-v1", max_requests=8)
        plan = {"model": "fixture-model-v1", "messages": [{"role": "user", "content": "Produce a bounded research plan"}]}
        extra = {"type": "function", "function": {"name": "execute"}}
        with self.assertRaises(StubRejected):
            model.answer({**plan, "tools": [extra]}, "stage-aurora-1")
        retrieve = {"model": "fixture-model-v1", "messages": [{"role": "user", "content": "Inspect only the admitted fixed synthetic fixture sources"}]}
        with self.assertRaises(StubRejected):
            model.answer({**retrieve, "tools": [{"type": "function", "function": {"name": "read_fixture"}}, extra]}, "stage-aurora-1")
        self.assertEqual(model.requests, 0)

    def test_host_audit_records_only_tool_names_and_request_count(self):
        with tempfile.TemporaryDirectory() as directory:
            audit = Path(directory) / "model-audit.jsonl"
            model = FixtureModel("stage-aurora-1", "fixture-model-v1", max_requests=8, audit_file=audit)
            model.answer({"model": "fixture-model-v1", "messages": [{"role": "user", "content": "Produce a bounded research plan"}]}, "stage-aurora-1")
            event = json.loads(audit.read_text().strip())
        self.assertEqual(event["request_number"], 1)
        self.assertEqual(event["effective_tools"], [])
        self.assertNotIn("Produce a bounded", event)

    def test_host_audit_refuses_stale_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            audit = Path(directory) / "model-audit.jsonl"
            audit.write_text("stale event\n")
            with self.assertRaises((ValueError, OSError)):
                FixtureModel("stage-aurora-1", "fixture-model-v1", audit_file=audit)

    def test_rejected_effective_tool_names_are_safely_audited(self):
        with tempfile.TemporaryDirectory() as directory:
            audit = Path(directory) / "model-audit.jsonl"
            model = FixtureModel("stage-aurora-1", "fixture-model-v1", audit_file=audit)
            payload = {
                "model": "fixture-model-v1",
                "messages": [{"role": "user", "content": "Produce a bounded research plan"}],
                "tools": [{"type": "function", "function": {"name": "write_todos"}}],
            }
            with self.assertRaises(StubRejected):
                model.answer(payload, "stage-aurora-1")
            event = json.loads(audit.read_text().strip())
        self.assertEqual(event["decision"], "deny")
        self.assertEqual(event["effective_tools"], ["write_todos"])
        self.assertEqual(event["stage"], "plan")
        self.assertNotIn("Produce a bounded", json.dumps(event))

    def test_first_plan_request_is_audited_while_response_is_held_for_cancellation(self):
        with tempfile.TemporaryDirectory() as directory:
            audit = Path(directory) / "held-plan.jsonl"
            entered = threading.Event()
            release = threading.Event()

            def hold_response(seconds):
                self.assertEqual(seconds, 5)
                entered.set()
                self.assertTrue(release.wait(timeout=2))

            model = FixtureModel("stage-aurora-1", "fixture-model-v1", audit_file=audit, delay_first_response_seconds=5)
            payload = {"model": "fixture-model-v1", "messages": [{"role": "user", "content": "Produce a bounded research plan"}]}
            with patch("spike.model_stub.time.sleep", side_effect=hold_response):
                process = threading.Thread(target=model.answer, args=(payload, "stage-aurora-1"))
                process.start()
                self.assertTrue(entered.wait(timeout=2))
                self.assertTrue(process.is_alive())
                event = json.loads(audit.read_text(encoding="utf-8").strip())
                self.assertEqual(event["stage"], "plan")
                self.assertEqual(event["response_delay_seconds"], 5)
                self.assertEqual(event["effective_tools"], [])
                release.set()
                process.join(timeout=2)
                self.assertFalse(process.is_alive())


if __name__ == "__main__":
    unittest.main()
