"""Black-box checks for the case projection and MCP stdio process."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[3]
CASES = ROOT / "eval/corpus/v1/cases.json"
SOURCES = ROOT / "eval/corpus/v1/sources.json"
PROTOCOL_VERSION = "2025-11-25"


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )


def _request(
    request_id: int, method: str, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    request: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        request["params"] = params
    return request


def _initialize(request_id: int = 1, version: str = PROTOCOL_VERSION) -> dict[str, Any]:
    return _request(
        request_id,
        "initialize",
        {
            "protocolVersion": version,
            "capabilities": {},
            "clientInfo": {"name": "fixture-protocol-test", "version": "1.0"},
        },
    )


def _call(request_id: int, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return _request(request_id, "tools/call", {"name": name, "arguments": arguments})


def _tool_value(response: dict[str, Any]) -> dict[str, Any]:
    result = response["result"]
    value = result["structuredContent"]
    assert result["content"] == [
        {
            "type": "text",
            "text": json.dumps(value, ensure_ascii=False, separators=(",", ":")),
        }
    ]
    assert result.get("isError") is not True
    return value


class ProjectionTests(unittest.TestCase):
    def _generate(
        self, case_id: str, output: Path, cases: Path = CASES, sources: Path = SOURCES
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "eval.mcp_fixture.project",
                "--draft-local",
                "--case-id",
                case_id,
                "--cases",
                str(cases),
                "--sources",
                str(sources),
                "--output",
                str(output),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    @staticmethod
    def _modified_inputs(
        directory: Path, pack: dict[str, Any], corpus: dict[str, Any]
    ) -> tuple[Path, Path]:
        corpus["source_pack_digest"] = _canonical_digest(pack)
        sources_path = directory / "sources.json"
        cases_path = directory / "cases.json"
        sources_path.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
        cases_path.write_text(json.dumps(corpus, ensure_ascii=False), encoding="utf-8")
        return cases_path, sources_path

    def test_all_24_cases_project_only_their_allowed_source_records(self) -> None:
        corpus = json.loads(CASES.read_text(encoding="utf-8"))
        pack = json.loads(SOURCES.read_text(encoding="utf-8"))
        source_by_id = {source["evidence_id"]: source for source in pack["sources"]}
        self.assertEqual(len(corpus["cases"]), 24)

        with tempfile.TemporaryDirectory() as directory:
            for case in corpus["cases"]:
                case_id = case["case_id"]
                with self.subTest(case_id=case_id):
                    output = Path(directory) / f"{case_id}.json"
                    process = self._generate(case_id, output)
                    self.assertEqual(process.returncode, 0, process.stderr)
                    status = json.loads(process.stdout)
                    projection = json.loads(output.read_text(encoding="utf-8"))
                    self.assertEqual(status["case_id"], case_id)
                    self.assertEqual(
                        status["projection_sha256"],
                        hashlib.sha256(output.read_bytes()).hexdigest(),
                    )
                    first_allowed_id = case["allowed_evidence_ids"][0]
                    served = subprocess.run(
                        [
                            sys.executable,
                            "-m",
                            "eval.mcp_fixture.server",
                            "--draft-local",
                            "--projection",
                            str(output),
                            "--case-id",
                            case_id,
                            "--projection-sha256",
                            status["projection_sha256"],
                        ],
                        cwd=ROOT,
                        input="\n".join(
                            json.dumps(message, separators=(",", ":"))
                            for message in (
                                _initialize(),
                                {
                                    "jsonrpc": "2.0",
                                    "method": "notifications/initialized",
                                },
                                _call(2, "fetch", {"id": first_allowed_id}),
                            )
                        )
                        + "\n",
                        capture_output=True,
                        text=True,
                        timeout=5,
                        check=False,
                    )
                    self.assertEqual(served.returncode, 0, served.stderr)
                    served_responses = [
                        json.loads(line) for line in served.stdout.splitlines()
                    ]
                    self.assertEqual(
                        _tool_value(served_responses[1])["id"], first_allowed_id
                    )
                    self.assertEqual(projection["case_id"], case_id)
                    self.assertEqual(
                        projection["source_pack_digest"], _canonical_digest(pack)
                    )
                    self.assertEqual(
                        projection["corpus_digest"], _canonical_digest(corpus)
                    )
                    self.assertEqual(
                        {source["id"] for source in projection["sources"]},
                        set(case["allowed_evidence_ids"]),
                    )
                    self.assertTrue(
                        all(source["url"] == "" for source in projection["sources"])
                    )
                    for source in projection["sources"]:
                        self.assertEqual(
                            source["text"], source_by_id[source["id"]]["text"]
                        )
                        self.assertEqual(
                            set(source), {"id", "title", "text", "url", "metadata"}
                        )
                    serialized = output.read_text(encoding="utf-8")
                    for evaluator_only in (
                        "expected_facts",
                        "expected_behavior",
                        "expected_citation_spans",
                        "forbidden_evidence_ids",
                        "prompt_injection_sentinel",
                    ):
                        self.assertNotIn(evaluator_only, serialized)
                    for forbidden_id in case["forbidden_evidence_ids"]:
                        self.assertNotIn(forbidden_id, serialized)

    def test_case_17_has_no_team_b_marker_or_denied_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "case-17.json"
            self.assertEqual(self._generate("case-17", output).returncode, 0)
            projection_text = output.read_text(encoding="utf-8")
            self.assertNotIn("acl-b", projection_text)
            self.assertNotIn("BASIL GOLD", projection_text)

    def test_projection_rejects_unknown_case_unapproved_class_and_source_pack_drift(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            unknown = self._generate("case-99", temp / "unknown.json")
            self.assertNotEqual(unknown.returncode, 0)
            self.assertFalse((temp / "unknown.json").exists())

            pack = json.loads(SOURCES.read_text(encoding="utf-8"))
            pack["sources"][0]["data_class"] = "private"
            modified_sources = temp / "private-sources.json"
            modified_sources.write_text(json.dumps(pack), encoding="utf-8")
            private = self._generate(
                "case-01", temp / "private.json", sources=modified_sources
            )
            self.assertNotEqual(private.returncode, 0)
            self.assertFalse((temp / "private.json").exists())

            pack = json.loads(SOURCES.read_text(encoding="utf-8"))
            pack["sources"][0]["text"] += " altered"
            modified_sources.write_text(json.dumps(pack), encoding="utf-8")
            drift = self._generate(
                "case-01", temp / "drift.json", sources=modified_sources
            )
            self.assertNotEqual(drift.returncode, 0)
            self.assertFalse((temp / "drift.json").exists())

    def test_projection_rejects_unreviewed_url_and_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            pack = json.loads(SOURCES.read_text(encoding="utf-8"))
            pack["sources"][0]["url"] = "https://example.invalid/fabricated"
            altered_sources = temp / "altered-sources.json"
            altered_sources.write_text(json.dumps(pack), encoding="utf-8")
            invalid = self._generate(
                "case-01", temp / "invalid.json", sources=altered_sources
            )
            self.assertNotEqual(invalid.returncode, 0)
            self.assertFalse((temp / "invalid.json").exists())

            output = temp / "case-17.json"
            self.assertEqual(self._generate("case-17", output).returncode, 0)
            before = output.read_bytes()
            overwrite = self._generate("case-20", output)
            self.assertNotEqual(overwrite.returncode, 0)
            self.assertEqual(output.read_bytes(), before)

    def test_projection_rejects_source_ids_the_server_cannot_load(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            pack = json.loads(SOURCES.read_text(encoding="utf-8"))
            corpus = json.loads(CASES.read_text(encoding="utf-8"))
            original = pack["sources"][0]["evidence_id"]
            invalid = f"{original} with spaces"
            pack["sources"][0]["evidence_id"] = invalid
            selected_case = next(
                case["case_id"]
                for case in corpus["cases"]
                if original in case["allowed_evidence_ids"]
            )
            for case in corpus["cases"]:
                for field in ("allowed_evidence_ids", "forbidden_evidence_ids"):
                    case[field] = [
                        invalid if item == original else item for item in case[field]
                    ]
            cases_path, sources_path = self._modified_inputs(temp, pack, corpus)
            output = temp / "invalid-id.json"
            process = self._generate(selected_case, output, cases_path, sources_path)
            self.assertNotEqual(process.returncode, 0, process.stdout)
            self.assertFalse(output.exists())

    def test_projection_rejects_file_larger_than_server_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            pack = json.loads(SOURCES.read_text(encoding="utf-8"))
            corpus = json.loads(CASES.read_text(encoding="utf-8"))
            selected = next(
                case for case in corpus["cases"] if case["case_id"] == "case-17"
            )
            for source in pack["sources"]:
                if source["evidence_id"] in selected["allowed_evidence_ids"]:
                    source["text"] = "x" * 4096
            for index in range(14):
                evidence_id = f"extra-{index:02d}"
                pack["sources"].append(
                    {
                        "evidence_id": evidence_id,
                        "data_class": "synthetic",
                        "origin": "generated",
                        "text": "x" * 4096,
                    }
                )
                selected["allowed_evidence_ids"].append(evidence_id)
            cases_path, sources_path = self._modified_inputs(temp, pack, corpus)
            output = temp / "oversized-projection.json"
            process = self._generate("case-17", output, cases_path, sources_path)
            self.assertNotEqual(process.returncode, 0, process.stdout)
            self.assertFalse(output.exists())

    def test_projection_rejects_fetch_that_exceeds_response_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            pack = json.loads(SOURCES.read_text(encoding="utf-8"))
            corpus = json.loads(CASES.read_text(encoding="utf-8"))
            source = next(
                item for item in pack["sources"] if item["evidence_id"] == "acl-a"
            )
            for emoji_count in (2300, 4096):
                with self.subTest(emoji_count=emoji_count):
                    source["text"] = "😀" * emoji_count
                    cases_path, sources_path = self._modified_inputs(temp, pack, corpus)
                    output = temp / f"oversized-fetch-{emoji_count}.json"
                    process = self._generate(
                        "case-17", output, cases_path, sources_path
                    )
                    self.assertNotEqual(process.returncode, 0, process.stdout)
                    self.assertFalse(output.exists())

    def test_projection_rejects_search_that_exceeds_worst_case_response_bound(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            pack = json.loads(SOURCES.read_text(encoding="utf-8"))
            corpus = json.loads(CASES.read_text(encoding="utf-8"))
            selected = next(
                case for case in corpus["cases"] if case["case_id"] == "case-17"
            )
            for index in range(14):
                evidence_id = f"extra-{index:02d}"
                pack["sources"].append(
                    {
                        "evidence_id": evidence_id,
                        "data_class": "synthetic",
                        "origin": "😀" * 200,
                        "text": "x",
                    }
                )
                selected["allowed_evidence_ids"].append(evidence_id)
            cases_path, sources_path = self._modified_inputs(temp, pack, corpus)
            output = temp / "oversized-search.json"
            process = self._generate("case-17", output, cases_path, sources_path)
            self.assertNotEqual(process.returncode, 0, process.stdout)
            self.assertFalse(output.exists())

    def test_projection_rejects_duplicate_json_keys_in_source_pack_and_corpus(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            for target in ("sources", "cases"):
                with self.subTest(target=target):
                    source_path = SOURCES
                    cases_path = CASES
                    original_path = SOURCES if target == "sources" else CASES
                    value = json.loads(original_path.read_text(encoding="utf-8"))
                    raw = json.dumps(value)
                    duplicate = raw.replace(
                        '"schema_version": 1,',
                        '"schema_version": 1, "schema_version": 1,',
                        1,
                    )
                    modified = temp / f"duplicate-{target}.json"
                    modified.write_text(duplicate, encoding="utf-8")
                    if target == "sources":
                        source_path = modified
                    else:
                        cases_path = modified
                    output = temp / f"duplicate-{target}-projection.json"
                    process = self._generate("case-17", output, cases_path, source_path)
                    self.assertNotEqual(process.returncode, 0, process.stdout)
                    self.assertFalse(output.exists())


class StdioProtocolTests(unittest.TestCase):
    temp: tempfile.TemporaryDirectory[str]
    projection: Path
    sha256: str

    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory()
        cls.projection = Path(cls.temp.name) / "case-17.json"
        generated = ProjectionTests()._generate("case-17", cls.projection)
        assert generated.returncode == 0, generated.stderr
        cls.sha256 = hashlib.sha256(cls.projection.read_bytes()).hexdigest()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def _exchange(self, *messages: dict[str, Any] | str) -> list[dict[str, Any]]:
        encoded_lines = [
            message
            if isinstance(message, str)
            else json.dumps(message, separators=(",", ":"))
            for message in messages
        ]
        process = subprocess.run(
            [
                sys.executable,
                "-m",
                "eval.mcp_fixture.server",
                "--draft-local",
                "--projection",
                str(self.projection),
                "--case-id",
                "case-17",
                "--projection-sha256",
                self.sha256,
            ],
            cwd=ROOT,
            input="\n".join(encoded_lines) + "\n",
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        return [json.loads(line) for line in process.stdout.splitlines()]

    def _ready(self) -> tuple[dict[str, Any], dict[str, Any]]:
        return _initialize(), {"jsonrpc": "2.0", "method": "notifications/initialized"}

    def test_initialize_probe_ping_and_tool_discovery(self) -> None:
        init, ready = self._ready()
        responses = self._exchange(
            _request(10, "server/discover"),
            init,
            ready,
            _request(2, "ping"),
            _request(3, "tools/list"),
        )
        self.assertEqual([response["id"] for response in responses], [10, 1, 2, 3])
        self.assertEqual(responses[0]["error"]["code"], -32601)
        self.assertEqual(responses[1]["result"]["protocolVersion"], PROTOCOL_VERSION)
        self.assertEqual(responses[1]["result"]["capabilities"], {"tools": {}})
        self.assertEqual(responses[2]["result"], {})
        tools = responses[3]["result"]["tools"]
        self.assertEqual([tool["name"] for tool in tools], ["search", "fetch"])
        for tool in tools:
            Draft202012Validator.check_schema(tool["inputSchema"])
            Draft202012Validator.check_schema(tool["outputSchema"])
            self.assertEqual(tool["inputSchema"]["additionalProperties"], False)
            self.assertTrue(tool["annotations"]["readOnlyHint"])

    def test_2025_06_18_client_receives_its_requested_version_and_tools(self) -> None:
        responses = self._exchange(
            _initialize(version="2025-06-18"),
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            _request(2, "tools/list"),
            _call(3, "fetch", {"id": "acl-a"}),
        )
        self.assertEqual(responses[0]["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(
            [tool["name"] for tool in responses[1]["result"]["tools"]],
            ["search", "fetch"],
        )
        self.assertEqual(_tool_value(responses[2])["id"], "acl-a")

    def test_selected_case_search_and_fetch_have_exact_openai_shapes(self) -> None:
        init, ready = self._ready()
        responses = self._exchange(
            init,
            ready,
            _request(2, "tools/list"),
            _call(3, "search", {"query": "Team A release marker"}),
            _call(4, "fetch", {"id": "acl-a"}),
        )
        tools = {tool["name"]: tool for tool in responses[1]["result"]["tools"]}
        search = _tool_value(responses[2])
        fetch = _tool_value(responses[3])
        Draft202012Validator(tools["search"]["outputSchema"]).validate(search)
        Draft202012Validator(tools["fetch"]["outputSchema"]).validate(fetch)
        self.assertEqual(set(search), {"results"})
        self.assertEqual(
            {result["id"] for result in search["results"]}, {"acl-a", "acl-public"}
        )
        self.assertTrue(
            all(set(result) == {"id", "title", "url"} for result in search["results"])
        )
        self.assertTrue(all(result["url"] == "" for result in search["results"]))
        self.assertEqual(set(fetch), {"id", "title", "text", "url", "metadata"})
        self.assertEqual(fetch["id"], "acl-a")
        self.assertIn("AURORA GREEN", fetch["text"])
        self.assertEqual(fetch["url"], "")
        self.assertEqual(fetch["metadata"]["data_class"], "synthetic")

    def test_forbidden_other_case_and_unknown_ids_have_uniform_denial(self) -> None:
        init, ready = self._ready()
        responses = self._exchange(
            init,
            ready,
            _call(2, "fetch", {"id": "acl-b"}),
            _call(3, "fetch", {"id": "pub-launch-final"}),
            _call(4, "fetch", {"id": "does-not-exist"}),
        )
        denied = [response["result"] for response in responses[1:]]
        self.assertEqual(denied[0], denied[1])
        self.assertEqual(denied[1], denied[2])
        self.assertTrue(denied[0]["isError"])
        self.assertNotIn("structuredContent", denied[0])
        self.assertNotIn("BASIL GOLD", json.dumps(responses))

    def test_write_tools_and_other_capabilities_are_not_available(self) -> None:
        init, ready = self._ready()
        responses = self._exchange(
            init,
            ready,
            _call(2, "write", {"id": "acl-a", "text": "changed"}),
            _request(3, "resources/list"),
            _request(4, "prompts/list"),
            _call(5, "fetch", {"id": "acl-a"}),
        )
        self.assertEqual(responses[1]["error"]["code"], -32602)
        self.assertEqual(responses[2]["error"]["code"], -32601)
        self.assertEqual(responses[3]["error"]["code"], -32601)
        self.assertIn("AURORA GREEN", _tool_value(responses[4])["text"])

    def test_malformed_and_oversized_input_recovers_without_echo(self) -> None:
        init, ready = self._ready()
        oversized = json.dumps(_call(8, "search", {"query": "X" * 20_000}))
        responses = self._exchange(
            init,
            ready,
            "{bad-json",
            _call(3, "search", {"query": ""}),
            _call(4, "search", {"query": "Q" * 257}),
            _call(5, "fetch", {"id": "acl-a", "case_id": "case-20"}),
            _call(6, "fetch", {"id": 5}),
            oversized,
            _request(9, "ping"),
        )
        self.assertEqual(
            [response.get("id") for response in responses],
            [1, None, 3, 4, 5, 6, None, 9],
        )
        self.assertEqual(responses[1]["error"]["code"], -32700)
        self.assertTrue(responses[2]["result"]["isError"])
        self.assertTrue(responses[3]["result"]["isError"])
        self.assertEqual(responses[4]["error"]["code"], -32602)
        self.assertEqual(responses[5]["error"]["code"], -32602)
        self.assertEqual(responses[6]["error"]["code"], -32600)
        self.assertEqual(responses[7]["result"], {})
        self.assertNotIn("X" * 100, json.dumps(responses))

    def test_lone_surrogate_request_ids_do_not_kill_the_stdio_session(self) -> None:
        init, ready = self._ready()
        responses = self._exchange(
            init,
            ready,
            r'{"jsonrpc":"2.0","id":"\ud800","method":"ping"}',
            r'{"jsonrpc":"2.0","id":"\udc00","method":"ping"}',
            _request(9, "ping"),
            r'{"jsonrpc":"2.0","id":"\ud83d\ude00","method":"ping"}',
        )
        self.assertEqual(
            [response.get("id") for response in responses], [1, None, None, 9, "😀"]
        )
        self.assertEqual(responses[1]["error"]["code"], -32600)
        self.assertEqual(responses[2]["error"]["code"], -32600)
        self.assertEqual(responses[3]["result"], {})
        self.assertEqual(responses[4]["result"], {})

    def test_server_rejects_wrong_case_or_modified_projection_before_stdio(
        self,
    ) -> None:
        wrong_case = subprocess.run(
            [
                sys.executable,
                "-m",
                "eval.mcp_fixture.server",
                "--draft-local",
                "--projection",
                str(self.projection),
                "--case-id",
                "case-20",
                "--projection-sha256",
                self.sha256,
            ],
            cwd=ROOT,
            input="",
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(wrong_case.returncode, 0)
        self.assertEqual(wrong_case.stdout, "")
        with tempfile.TemporaryDirectory() as directory:
            modified = Path(directory) / "modified.json"
            modified.write_bytes(self.projection.read_bytes() + b" ")
            process = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "eval.mcp_fixture.server",
                    "--draft-local",
                    "--projection",
                    str(modified),
                    "--case-id",
                    "case-17",
                    "--projection-sha256",
                    self.sha256,
                ],
                cwd=ROOT,
                input="",
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(process.returncode, 0)
            self.assertEqual(process.stdout, "")

    def test_server_rejects_duplicate_json_keys_in_projection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            modified = Path(directory) / "duplicate.json"
            raw = self.projection.read_bytes().replace(
                b'"case_id":"case-17"',
                b'"case_id":"case-17","case_id":"case-17"',
                1,
            )
            modified.write_bytes(raw)
            process = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "eval.mcp_fixture.server",
                    "--draft-local",
                    "--projection",
                    str(modified),
                    "--case-id",
                    "case-17",
                    "--projection-sha256",
                    hashlib.sha256(raw).hexdigest(),
                ],
                cwd=ROOT,
                input="",
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(process.returncode, 0)
            self.assertEqual(process.stdout, "")

    def test_server_refuses_lone_surrogate_projection_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            modified = Path(directory) / "surrogate.json"
            raw = self.projection.read_bytes().replace(b"AURORA GREEN", b"\\ud800", 1)
            self.assertNotEqual(raw, self.projection.read_bytes())
            modified.write_bytes(raw)
            process = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "eval.mcp_fixture.server",
                    "--draft-local",
                    "--projection",
                    str(modified),
                    "--case-id",
                    "case-17",
                    "--projection-sha256",
                    hashlib.sha256(raw).hexdigest(),
                ],
                cwd=ROOT,
                input="",
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(process.returncode, 2)
            self.assertEqual(process.stdout, "")
            self.assertNotIn("Traceback", process.stderr)


class ApprovedDistributionTests(unittest.TestCase):
    """Only temporary synthetic approval doubles are used; no human sign-off exists."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.corpus = json.loads(CASES.read_text(encoding="utf-8"))
        self.pack = json.loads(SOURCES.read_text(encoding="utf-8"))
        self.rubric = json.loads(
            (ROOT / "eval/corpus/v1/rubric.json").read_text(encoding="utf-8")
        )
        approved = {
            "status": "approved",
            "reviewer_id": "synthetic-test-reviewer",
            "reviewed_at": "2026-10-26T00:00:00Z",
        }
        self.corpus["approval"] = approved.copy()
        self.rubric["approval"] = approved.copy()
        self.cases_path = self.directory / "cases.json"
        self.sources_path = self.directory / "sources.json"
        self.rubric_path = self.directory / "rubric.json"
        self.manifest_path = self.directory / "approval-manifest.json"
        self._write_inputs()
        self._register_manifest()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write_inputs(self) -> None:
        self.cases_path.write_bytes(_canonical_bytes(self.corpus))
        self.sources_path.write_bytes(_canonical_bytes(self.pack))
        self.rubric_path.write_bytes(_canonical_bytes(self.rubric))

    def _expected_projection(self, case: dict[str, Any]) -> dict[str, Any]:
        source_by_id = {item["evidence_id"]: item for item in self.pack["sources"]}
        sources = []
        for evidence_id in sorted(case["allowed_evidence_ids"]):
            source = source_by_id[evidence_id]
            sources.append(
                {
                    "id": evidence_id,
                    "title": f"{source['origin']} / {evidence_id}",
                    "text": source["text"],
                    "url": "",
                    "metadata": {
                        "origin": source["origin"],
                        "data_class": source["data_class"],
                    },
                }
            )
        return {
            "schema_version": 2,
            "distribution_status": "approved_tester_view",
            "case_id": case["case_id"],
            "source_pack_id": self.pack["source_pack_id"],
            "source_pack_digest": _canonical_digest(self.pack),
            "corpus_digest": _canonical_digest(self.corpus),
            "citation_link_parity": "unproved",
            "sources": sources,
        }

    def _register_manifest(self) -> None:
        case_entries = []
        for case in self.corpus["cases"]:
            question_bytes = case["question"].encode("utf-8") + b"\n"
            projection_bytes = _canonical_bytes(self._expected_projection(case))
            case_entries.append(
                {
                    "case_id": case["case_id"],
                    "question_sha256": hashlib.sha256(question_bytes).hexdigest(),
                    "projection_sha256": hashlib.sha256(projection_bytes).hexdigest(),
                }
            )
        self.manifest = {
            "schema_version": 1,
            "approval": {
                "status": "approved",
                "reviewer_id": "synthetic-test-reviewer",
                "reviewed_at": "2026-10-26T00:00:00Z",
                "approval_ref": "test-double-only",
            },
            "data_use_destination": "chatgpt_enterprise",
            "corpus_sha256": hashlib.sha256(self.cases_path.read_bytes()).hexdigest(),
            "sources_sha256": hashlib.sha256(
                self.sources_path.read_bytes()
            ).hexdigest(),
            "rubric_sha256": hashlib.sha256(self.rubric_path.read_bytes()).hexdigest(),
            "cases": case_entries,
        }
        self.manifest_path.write_bytes(_canonical_bytes(self.manifest))
        self.registered_pin = hashlib.sha256(
            self.manifest_path.read_bytes()
        ).hexdigest()

    def _project(
        self,
        case_id: str = "case-17",
        packet_dir: Path | None = None,
        *,
        draft_local: bool = False,
        output: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = [
            sys.executable,
            "-m",
            "eval.mcp_fixture.project",
            "--case-id",
            case_id,
            "--cases",
            str(self.cases_path),
            "--sources",
            str(self.sources_path),
        ]
        if draft_local:
            command.extend(
                [
                    "--draft-local",
                    "--output",
                    str(output or self.directory / "draft.json"),
                ]
            )
        else:
            command.extend(
                [
                    "--rubric",
                    str(self.rubric_path),
                    "--approval-manifest",
                    str(self.manifest_path),
                    "--approved-manifest-sha256",
                    self.registered_pin,
                    "--packet-dir",
                    str(packet_dir or self.directory / "packet"),
                ]
            )
        return subprocess.run(
            command, cwd=ROOT, capture_output=True, text=True, check=False
        )

    def _serve(
        self,
        projection: Path,
        case_id: str = "case-17",
        *,
        draft_local: bool = False,
        supplied_sha: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = [
            sys.executable,
            "-m",
            "eval.mcp_fixture.server",
            "--projection",
            str(projection),
            "--case-id",
            case_id,
            "--projection-sha256",
            supplied_sha or hashlib.sha256(projection.read_bytes()).hexdigest(),
        ]
        if draft_local:
            command.append("--draft-local")
        else:
            command.extend(
                [
                    "--approval-manifest",
                    str(self.manifest_path),
                    "--approved-manifest-sha256",
                    self.registered_pin,
                ]
            )
        messages = [
            _initialize(),
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            _call(2, "fetch", {"id": "acl-a"}),
            _call(3, "fetch", {"id": "acl-b"}),
        ]
        return subprocess.run(
            command,
            cwd=ROOT,
            input="\n".join(json.dumps(message) for message in messages) + "\n",
            capture_output=True,
            text=True,
            check=False,
        )

    def test_approved_packet_directory_contains_both_complete_files(self) -> None:
        packet_dir = self.directory / "case-17-packet"
        command = [
            sys.executable,
            "-m",
            "eval.mcp_fixture.project",
            "--case-id",
            "case-17",
            "--cases",
            str(self.cases_path),
            "--sources",
            str(self.sources_path),
            "--rubric",
            str(self.rubric_path),
            "--approval-manifest",
            str(self.manifest_path),
            "--approved-manifest-sha256",
            self.registered_pin,
            "--packet-dir",
            str(packet_dir),
        ]
        result = subprocess.run(
            command, cwd=ROOT, capture_output=True, text=True, check=False
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            {item.name for item in packet_dir.iterdir()},
            {"question.txt", "projection.json"},
        )
        projection = packet_dir / "projection.json"
        selected = next(
            case for case in self.corpus["cases"] if case["case_id"] == "case-17"
        )
        self.assertEqual(
            (packet_dir / "question.txt").read_bytes(),
            selected["question"].encode() + b"\n",
        )
        self.assertEqual(
            json.loads(projection.read_bytes()), self._expected_projection(selected)
        )
        self.assertEqual(self._serve(projection).returncode, 0)

    def test_interruption_during_second_file_never_exposes_partial_packet(self) -> None:
        from eval.mcp_fixture import project

        packet_dir = self.directory / "interrupted-packet"
        question_data = b"synthetic question\n"
        projection_data = b"synthetic projection\n"
        real_open = project.os.open
        calls = 0

        def interrupt_second(
            path: Path, flags: int, mode: int = 0o777, **kwargs: Any
        ) -> int:
            nonlocal calls
            if Path(path).name in {"question.txt", "projection.json"}:
                calls += 1
                self.assertFalse(packet_dir.exists())
                self.assertEqual(Path(path).parent.stat().st_mode & 0o777, 0o700)
                if calls == 2:
                    raise KeyboardInterrupt("synthetic interruption")
            return real_open(path, flags, mode, **kwargs)

        with (
            patch.object(project.os, "open", side_effect=interrupt_second),
            self.assertRaises(KeyboardInterrupt),
        ):
            project._publish_packet_dir(
                packet_dir,
                question_data,
                projection_data,
                hashlib.sha256(question_data).hexdigest(),
                hashlib.sha256(projection_data).hexdigest(),
            )
        self.assertEqual(calls, 2)
        self.assertFalse(packet_dir.exists())
        self.assertEqual(list(self.directory.glob(".mcp-packet-staging-*")), [])

    def test_staged_digest_mismatch_leaves_no_packet(self) -> None:
        from eval.mcp_fixture import project

        packet_dir = self.directory / "mismatched-packet"
        question_data = b"synthetic question\n"
        projection_data = b"synthetic projection\n"
        with self.assertRaises(project.ProjectionError):
            project._publish_packet_dir(
                packet_dir,
                question_data,
                projection_data,
                hashlib.sha256(question_data).hexdigest(),
                "0" * 64,
            )
        self.assertFalse(packet_dir.exists())
        self.assertEqual(list(self.directory.glob(".mcp-packet-staging-*")), [])

    def test_approved_pin_releases_only_exact_one_case_question_and_view(self) -> None:
        schema = json.loads(
            (ROOT / "eval/mcp_fixture/approval-manifest.schema.json").read_text(
                encoding="utf-8"
            )
        )
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(self.manifest)
        packet = self.directory / "approved-packet"
        result = self._project(packet_dir=packet)
        self.assertEqual(result.returncode, 0, result.stderr)
        projection = packet / "projection.json"
        question = packet / "question.txt"
        selected = next(
            case for case in self.corpus["cases"] if case["case_id"] == "case-17"
        )
        self.assertEqual(question.read_bytes(), selected["question"].encode() + b"\n")
        self.assertEqual(
            json.loads(projection.read_bytes()), self._expected_projection(selected)
        )
        self.assertNotIn("acl-b", projection.read_text(encoding="utf-8"))
        self.assertNotIn("expected_facts", projection.read_text(encoding="utf-8"))
        served = self._serve(projection)
        self.assertEqual(served.returncode, 0, served.stderr)
        responses = [json.loads(line) for line in served.stdout.splitlines()]
        self.assertEqual(_tool_value(responses[1])["id"], "acl-a")
        self.assertTrue(responses[2]["result"]["isError"])

    def test_pending_corpus_or_rubric_refuses_before_writing_either_file(self) -> None:
        for field in ("corpus", "rubric"):
            with self.subTest(field=field):
                original = getattr(self, field)["approval"]
                getattr(self, field)["approval"] = {"status": "pending"}
                self._write_inputs()
                self._register_manifest()
                packet = self.directory / f"pending-{field}-packet"
                result = self._project(packet_dir=packet)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertFalse(packet.exists())
                getattr(self, field)["approval"] = original
                self._write_inputs()
                self._register_manifest()

    def test_changed_corpus_source_or_rubric_denies_even_when_self_rehashed(
        self,
    ) -> None:
        original_cases = self.cases_path.read_bytes()
        original_sources = self.sources_path.read_bytes()
        original_rubric = self.rubric_path.read_bytes()
        for target in ("corpus", "sources", "rubric"):
            with self.subTest(target=target):
                if target == "corpus":
                    self.corpus["cases"][16]["question"] += " changed"
                elif target == "sources":
                    self.pack["sources"][0]["text"] += " changed"
                    self.corpus["source_pack_digest"] = _canonical_digest(self.pack)
                else:
                    self.rubric["description"] += " changed"
                self._write_inputs()
                packet = self.directory / f"changed-{target}-packet"
                result = self._project(packet_dir=packet)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertFalse(packet.exists())
                self.cases_path.write_bytes(original_cases)
                self.sources_path.write_bytes(original_sources)
                self.rubric_path.write_bytes(original_rubric)
                self.corpus = json.loads(original_cases)
                self.pack = json.loads(original_sources)
                self.rubric = json.loads(original_rubric)

    def test_server_denies_self_rehashed_forbidden_record_and_wrong_case(self) -> None:
        packet = self.directory / "approved-packet"
        self.assertEqual(self._project(packet_dir=packet).returncode, 0)
        projection = packet / "projection.json"
        altered = json.loads(projection.read_bytes())
        forbidden = next(
            source
            for source in self.pack["sources"]
            if source["evidence_id"] == "acl-b"
        )
        altered["sources"].append(
            {
                "id": "acl-b",
                "title": f"{forbidden['origin']} / acl-b",
                "text": forbidden["text"],
                "url": "",
                "metadata": {
                    "origin": forbidden["origin"],
                    "data_class": forbidden["data_class"],
                },
            }
        )
        changed = self.directory / "self-rehashed.json"
        changed.write_bytes(_canonical_bytes(altered))
        denied = self._serve(changed)
        self.assertEqual(denied.returncode, 2, denied.stderr)
        self.assertEqual(denied.stdout, "")
        wrong_case = self._serve(projection, case_id="case-20")
        self.assertEqual(wrong_case.returncode, 2, wrong_case.stderr)
        self.assertEqual(wrong_case.stdout, "")

    def test_rehashed_manifest_without_registered_pin_and_partial_write_deny(
        self,
    ) -> None:
        changed = dict(self.manifest)
        approval = changed["approval"]
        assert isinstance(approval, dict)
        changed["approval"] = dict(approval, approval_ref="replacement")
        self.manifest_path.write_bytes(_canonical_bytes(changed))
        packet = self.directory / "changed-manifest-packet"
        denied = self._project(packet_dir=packet)
        self.assertEqual(denied.returncode, 2, denied.stderr)
        self.assertFalse(packet.exists())
        self._register_manifest()
        packet.mkdir()
        sentinel = packet / "sentinel.txt"
        sentinel.write_text("existing sentinel", encoding="utf-8")
        denied = self._project(packet_dir=packet)
        self.assertEqual(denied.returncode, 2, denied.stderr)
        self.assertEqual({item.name for item in packet.iterdir()}, {"sentinel.txt"})
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "existing sentinel")

    def test_self_pinned_pending_manifest_and_default_server_mode_deny(self) -> None:
        approved_packet = self.directory / "approved-packet"
        self.assertEqual(self._project(packet_dir=approved_packet).returncode, 0)
        projection = approved_packet / "projection.json"
        missing_approval = subprocess.run(
            [
                sys.executable,
                "-m",
                "eval.mcp_fixture.server",
                "--projection",
                str(projection),
                "--case-id",
                "case-17",
                "--projection-sha256",
                hashlib.sha256(projection.read_bytes()).hexdigest(),
            ],
            cwd=ROOT,
            input="",
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(missing_approval.returncode, 2)
        self.assertEqual(missing_approval.stdout, "")
        approval = self.manifest["approval"]
        assert isinstance(approval, dict)
        approval["status"] = "pending"
        self.manifest_path.write_bytes(_canonical_bytes(self.manifest))
        self.registered_pin = hashlib.sha256(
            self.manifest_path.read_bytes()
        ).hexdigest()
        pending_packet = self.directory / "pending-manifest-packet"
        denied = self._project(packet_dir=pending_packet)
        self.assertEqual(denied.returncode, 2)
        self.assertFalse(pending_packet.exists())
        self.assertEqual(self._serve(projection).returncode, 2)

    def test_generated_candidate_is_pending_and_its_self_hash_cannot_authorize(
        self,
    ) -> None:
        candidate_path = self.directory / "manifest-candidate.json"
        prepared = subprocess.run(
            [
                sys.executable,
                "-m",
                "eval.mcp_fixture.project",
                "--cases",
                str(self.cases_path),
                "--sources",
                str(self.sources_path),
                "--rubric",
                str(self.rubric_path),
                "--prepare-manifest-candidate",
                str(candidate_path),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        self.assertEqual(
            json.loads(prepared.stdout)["approval_status"], "PENDING_NON_AUTHORIZING"
        )
        candidate = json.loads(candidate_path.read_bytes())
        self.assertEqual(candidate["approval"], {"status": "pending"})
        self.assertEqual(len(candidate["cases"]), 24)
        self.assertEqual(candidate["cases"], self.manifest["cases"])
        self.assertNotIn("expected_facts", candidate_path.read_text(encoding="utf-8"))
        self.assertNotIn("BASIL GOLD", candidate_path.read_text(encoding="utf-8"))
        candidate_pin = hashlib.sha256(candidate_path.read_bytes()).hexdigest()
        packet = self.directory / "candidate-packet"
        denied_project = subprocess.run(
            [
                sys.executable,
                "-m",
                "eval.mcp_fixture.project",
                "--case-id",
                "case-17",
                "--cases",
                str(self.cases_path),
                "--sources",
                str(self.sources_path),
                "--rubric",
                str(self.rubric_path),
                "--approval-manifest",
                str(candidate_path),
                "--approved-manifest-sha256",
                candidate_pin,
                "--packet-dir",
                str(packet),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(denied_project.returncode, 2)
        self.assertFalse(packet.exists())
        approved_packet = self.directory / "approved-packet"
        self.assertEqual(self._project(packet_dir=approved_packet).returncode, 0)
        approved_projection = approved_packet / "projection.json"
        denied_server = subprocess.run(
            [
                sys.executable,
                "-m",
                "eval.mcp_fixture.server",
                "--case-id",
                "case-17",
                "--projection",
                str(approved_projection),
                "--projection-sha256",
                hashlib.sha256(approved_projection.read_bytes()).hexdigest(),
                "--approval-manifest",
                str(candidate_path),
                "--approved-manifest-sha256",
                candidate_pin,
            ],
            cwd=ROOT,
            input="",
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(denied_server.returncode, 2)
        self.assertEqual(denied_server.stdout, "")

    def test_draft_local_marker_cannot_pass_distribution(self) -> None:
        implicit = self.directory / "implicit-projection.json"
        implicit_mode = subprocess.run(
            [
                sys.executable,
                "-m",
                "eval.mcp_fixture.project",
                "--case-id",
                "case-17",
                "--output",
                str(implicit),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(implicit_mode.returncode, 2)
        self.assertFalse(implicit.exists())
        legacy_projection = self.directory / "legacy-approved-projection.json"
        legacy_question = self.directory / "legacy-approved-question.txt"
        old_two_file_form = subprocess.run(
            [
                sys.executable,
                "-m",
                "eval.mcp_fixture.project",
                "--case-id",
                "case-17",
                "--cases",
                str(self.cases_path),
                "--sources",
                str(self.sources_path),
                "--rubric",
                str(self.rubric_path),
                "--approval-manifest",
                str(self.manifest_path),
                "--approved-manifest-sha256",
                self.registered_pin,
                "--output",
                str(legacy_projection),
                "--question-output",
                str(legacy_question),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(old_two_file_form.returncode, 2)
        self.assertFalse(legacy_projection.exists())
        self.assertFalse(legacy_question.exists())
        draft = self.directory / "draft-only.json"
        result = self._project(output=draft, draft_local=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(draft.read_bytes())["distribution_status"],
            "draft_local_do_not_distribute",
        )
        self.assertEqual(self._serve(draft, draft_local=True).returncode, 0)
        denied = self._serve(draft)
        self.assertEqual(denied.returncode, 2, denied.stderr)
        self.assertEqual(denied.stdout, "")

    def test_second_output_write_failure_removes_first_output(self) -> None:
        from eval.mcp_fixture import project

        first = self.directory / "first.json"
        second = self.directory / "second.txt"
        real_open = project.os.open
        calls = 0

        def fail_second(path: Path, flags: int, mode: int) -> int:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("synthetic disk failure")
            return real_open(path, flags, mode)

        with (
            patch.object(project.os, "open", side_effect=fail_second),
            self.assertRaises(project.ProjectionError),
        ):
            project._write_new_files([(first, b"one"), (second, b"two")])
        self.assertFalse(first.exists())
        self.assertFalse(second.exists())


if __name__ == "__main__":
    unittest.main()
