import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from spike.contract import StageManifest, StageManifestError
from spike.evidence import EvidenceError, FixtureCorpus, FixtureReadTool
from spike.worker import ResearchWorker, WorkerError, build_graph, run_entrypoint

FIXTURE = Path(__file__).parents[1] / "fixtures" / "aurora-v1.json"


def manifest_dict(**changes):
    value = {
        "schema_version": "spike.stage.v1",
        "job_id": "job-aurora-1",
        "stage_id": "stage-aurora-1",
        "attempt_id": "attempt-1",
        "fixture_id": "aurora-v1",
        "data_class": "synthetic",
        "question": "Who owns Aurora and when did its runbook take effect?",
        "source_ids": ["ownership", "runbook"],
        "limits": {
            "max_sources": 2,
            "max_evidence_bytes": 512,
            "max_model_calls": 4,
            "max_response_chars": 2000,
        },
    }
    value.update(changes)
    return value


class StubAgent:
    def __init__(self):
        self.calls = []

    def invoke(self, step, prompt, *, tools=()):
        self.calls.append((step, prompt, tuple(tool.name for tool in tools)))
        if step == "plan":
            return "Read the two admitted fixture sources and cite exact quotes."
        if step == "retrieve":
            for source_id in ("ownership", "runbook"):
                tools[0].read(source_id)
            return "Ownership and effective date are present in the retained snapshots."
        if step == "synthesize":
            return json.dumps({"claims": [
                {"text": "Team Atlas owns Aurora.", "source_id": "ownership", "quote": "Team Atlas owns Project Aurora."},
                {"text": "The runbook took effect on 2026-02-01.", "source_id": "runbook", "quote": "The Aurora runbook took effect on 2026-02-01."},
            ], "limitations": "Only the fixed synthetic sources were reviewed."})
        if step == "verify":
            return '{"approved": true}'
        raise AssertionError(step)


class FakeGraph:
    def __init__(self, state_type):
        self.nodes = {}
        self.edges = []

    def add_node(self, name, node):
        self.nodes[name] = node

    def add_edge(self, a, b):
        self.edges.append((a, b))

    def compile(self):
        return self

    def invoke(self, state, config=None):
        current = "__start__"
        while current != "__end__":
            next_nodes = [b for a, b in self.edges if a == current]
            if len(next_nodes) != 1:
                raise AssertionError(f"ambiguous graph after {current}")
            current = next_nodes[0]
            if current != "__end__":
                state.update(self.nodes[current](state))
        return state


class WorkerTests(unittest.TestCase):
    def test_graph_has_fixed_bounded_order(self):
        agent = StubAgent()
        worker = ResearchWorker(agent, FixtureCorpus.load(FIXTURE))
        graph = build_graph(worker, graph_type=FakeGraph)
        self.assertEqual(graph.edges, [
            ("__start__", "plan"),
            ("plan", "retrieve"),
            ("retrieve", "synthesize"),
            ("synthesize", "verify"),
            ("verify", "__end__"),
        ])
        result = worker.run(StageManifest.from_dict(manifest_dict()), "stage-aurora-1", graph_type=FakeGraph)
        self.assertEqual([step[0] for step in agent.calls], ["plan", "retrieve", "synthesize", "verify"])
        self.assertEqual([event["step"] for event in result["steps"]], ["plan", "retrieve", "synthesize", "verify"])
        self.assertTrue(result["verified"])
        self.assertEqual(len(result["report"]["claims"]), 2)
        self.assertTrue(all(claim["evidence_id"].startswith("ev_") for claim in result["report"]["claims"]))

    def test_entrypoint_runs_graph_in_current_worker_process(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stage.json"
            path.write_text(json.dumps(manifest_dict()))
            result = run_entrypoint(path, "stage-aurora-1", agent=StubAgent(), graph_type=FakeGraph)
        self.assertTrue(result["steps"])
        self.assertEqual({step["pid"] for step in result["steps"]}, {os.getpid()})
        self.assertEqual(result["stage_id"], "stage-aurora-1")

    def test_wrong_stage_id_fails_before_any_model_call(self):
        agent = StubAgent()
        worker = ResearchWorker(agent, FixtureCorpus.load(FIXTURE))
        with self.assertRaises(StageManifestError):
            worker.run(StageManifest.from_dict(manifest_dict()), "other-stage", graph_type=FakeGraph)
        self.assertEqual(agent.calls, [])

    def test_fixed_fixture_and_total_evidence_bound(self):
        corpus = FixtureCorpus.load(FIXTURE)
        manifest = StageManifest.from_dict(manifest_dict())
        selected = corpus.select(manifest)
        self.assertEqual([item.source_id for item in selected], ["ownership", "runbook"])
        self.assertLessEqual(sum(len(item.text.encode()) for item in selected), manifest.limits.max_evidence_bytes)
        self.assertEqual(selected[0].evidence_id, corpus.select(manifest)[0].evidence_id)
        with self.assertRaises(EvidenceError):
            corpus.select(StageManifest.from_dict(manifest_dict(source_ids=["unlisted"])))
        with self.assertRaises(EvidenceError):
            corpus.select(StageManifest.from_dict(manifest_dict(limits={
                "max_sources": 2, "max_evidence_bytes": 64,
                "max_model_calls": 4, "max_response_chars": 2000,
            })))

    def test_retrieval_requires_observed_tool_reads_and_does_not_preembed_source_text(self):
        agent = StubAgent()
        stage = StageManifest.from_dict(manifest_dict())
        result = ResearchWorker(agent, FixtureCorpus.load(FIXTURE)).run(stage, stage.stage_id, graph_type=FakeGraph)
        retrieval_prompt = next(prompt for step, prompt, _ in agent.calls if step == "retrieve")
        self.assertNotIn("Team Atlas owns Project Aurora", retrieval_prompt)
        self.assertNotIn("The Aurora runbook took effect", retrieval_prompt)
        self.assertEqual(
            [(entry["source_id"], entry["decision"]) for entry in result["retrieval_tool_calls"]],
            [("ownership", "allow"), ("runbook", "allow")],
        )

        class NoRead(StubAgent):
            def invoke(self, step, prompt, *, tools=()):
                if step == "retrieve":
                    return "I already know the answer."
                return super().invoke(step, prompt, tools=tools)

        with self.assertRaisesRegex(WorkerError, "read_fixture"):
            ResearchWorker(NoRead(), FixtureCorpus.load(FIXTURE)).run(stage, stage.stage_id, graph_type=FakeGraph)

    def test_unadmitted_fixture_id_denial_is_recorded_by_same_tool(self):
        stage = StageManifest.from_dict(manifest_dict())
        tool = FixtureReadTool(FixtureCorpus.load(FIXTURE).select(stage))
        with self.assertRaisesRegex(EvidenceError, "not admitted"):
            tool.read("decoy")
        self.assertEqual(tool.observations, [{"source_id": "decoy", "decision": "deny"}])

        from spike import worker

        probe = worker.run_source_denial_probe(stage, stage.stage_id, "decoy", FixtureCorpus.load(FIXTURE))
        self.assertEqual(probe, {"source_id": "decoy", "decision": "deny", "stage_id": stage.stage_id})

    def test_worker_rejects_host_openai_key_inherited_into_sandbox(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stage.json"
            path.write_text(json.dumps(manifest_dict()))
            with patch.dict(os.environ, {"RESEARCH_OPENAI_API_KEY": "test-only-secret"}), self.assertRaisesRegex(WorkerError, "RESEARCH_OPENAI_API_KEY"):
                run_entrypoint(path, "stage-aurora-1", agent=StubAgent(), graph_type=FakeGraph)

    def test_actual_http_model_request_budget_counts_tool_round_trip(self):
        from spike.worker import DeepAgentClient

        deepagents = types.ModuleType("deepagents")
        langchain_openai = types.ModuleType("langchain_openai")
        created = []
        profiles = []

        class FakeChatOpenAI:
            def __init__(self, **kwargs):
                self.http_client = kwargs["http_client"]
                self.default_headers = kwargs["default_headers"]

        def create_deep_agent(*, model, tools, **kwargs):
            created.append((model, tools))

            class FakeAgent:
                def invoke(self, payload, config=None):
                    model.http_client.post("http://relay.spike.internal:8765/v1/chat/completions", json={"turn": "call-tool"})
                    tools[0]("ownership")
                    model.http_client.post("http://relay.spike.internal:8765/v1/chat/completions", json={"turn": "tool-result"})
                    return {"messages": [SimpleNamespace(content="Source read completed.")]}

            return FakeAgent()

        deepagents.create_deep_agent = create_deep_agent
        deepagents.register_harness_profile = lambda *a, **kw: None
        def make_profile(**kwargs):
            profiles.append(kwargs)
            return object()

        deepagents.HarnessProfile = make_profile
        deepagents.GeneralPurposeSubagentProfile = lambda **kw: object()
        langchain_openai.ChatOpenAI = FakeChatOpenAI
        response = lambda request: httpx.Response(200, json={"ok": True})
        corpus = FixtureCorpus.load(FIXTURE)
        tool = FixtureReadTool(corpus.select(StageManifest.from_dict(manifest_dict())))
        with patch.dict(sys.modules, {"deepagents": deepagents, "langchain_openai": langchain_openai}):
            client = DeepAgentClient(
                "http://relay.spike.internal:8765/v1", "fixture-model-v1", "stage-aurora-1", 256,
                max_model_requests=2, data_class="synthetic", http_transport=httpx.MockTransport(response),
            )
            try:
                self.assertTrue(client.http_client._trust_env)
                self.assertEqual(client.invoke("retrieve", "Read ownership", tools=(tool,)), "Source read completed.")
                self.assertEqual(client.model_requests_observed, 2)
                with self.assertRaisesRegex(WorkerError, "model request limit"):
                    client.invoke("retrieve", "Read ownership", tools=(tool,))
                self.assertEqual(client.model_requests_observed, 2)
            finally:
                client.close()
        self.assertEqual(len(created), 2)
        self.assertEqual(created[0][0].default_headers["X-Research-Data-Class"], "synthetic")
        self.assertTrue(profiles)
        self.assertTrue(all("delete" in profile["excluded_tools"] for profile in profiles))

    def test_invalid_quote_and_model_rejection_do_not_complete(self):
        class BadQuote(StubAgent):
            def invoke(self, step, prompt, *, tools=()):
                if step == "synthesize":
                    return json.dumps({"claims": [{"text": "False claim", "source_id": "ownership", "quote": "never in the snapshot"}], "limitations": ""})
                return super().invoke(step, prompt, tools=tools)

        manifest = StageManifest.from_dict(manifest_dict())
        with self.assertRaises(WorkerError):
            ResearchWorker(BadQuote(), FixtureCorpus.load(FIXTURE)).run(manifest, manifest.stage_id, graph_type=FakeGraph)


if __name__ == "__main__":
    unittest.main()
