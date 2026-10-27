"""Preapproval fairness and evaluator/tester separation checks for the draft pack."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import unittest
from pathlib import Path
from typing import Any

from eval.mcp_fixture import project, server

CORPUS_ROOT = Path(__file__).resolve().parents[1] / "corpus/v1"
EVALUATOR_ONLY_KEYS = {
    "category",
    "case_setup",
    "expected_behavior",
    "expected_facts",
    "expected_citation_spans",
    "forbidden_evidence_ids",
    "permission_subject_id",
    "permission_target_evidence_id",
    "prompt_injection_sentinel",
    "rubric_dimensions",
}


def _read(name: str) -> dict[str, Any]:
    return json.loads((CORPUS_ROOT / name).read_text(encoding="utf-8"))


def _case(corpus: dict[str, Any], case_id: str) -> dict[str, Any]:
    return next(case for case in corpus["cases"] if case["case_id"] == case_id)


class CorpusReadinessTests(unittest.TestCase):
    def test_evaluator_review_cover_pins_exact_draft_input_bytes(self) -> None:
        cover = (CORPUS_ROOT / "approval-review-draft.md").read_text(encoding="utf-8")
        self.assertIn("**Status: draft", cover)
        for filename in ("cases.json", "sources.json", "rubric.json"):
            with self.subTest(input=filename):
                path = CORPUS_ROOT / filename
                raw_digest = hashlib.sha256(path.read_bytes()).hexdigest()
                canonical_digest = project._digest(_read(filename))
                self.assertIn(
                    f"| `{filename}` raw / canonical SHA-256 | "
                    f"`{raw_digest}` / `{canonical_digest}` |",
                    cover,
                )

    def test_time_questions_have_temporally_complete_review_anchors(self) -> None:
        corpus = _read("cases.json")
        approval = _case(corpus, "case-07")
        self.assertIn("at what time", approval["question"].lower())
        self.assertTrue(
            any(
                "13:20 UTC" in span["quote"]
                for span in approval["expected_citation_spans"]
            ),
            "case-07 must anchor the time it asks the candidate to report",
        )

        canary = _case(corpus, "case-09")
        self.assertIn("15:30 UTC", canary["question"])
        expectation = " ".join(canary["expected_facts"]).lower()
        self.assertIn("paused", expectation)
        self.assertIn("15:00", expectation)
        self.assertIn("16:00", expectation)
        self.assertRegex(
            expectation,
            r"(not yet|had not|only later|later).*?(disabled|disabling|disablement|merged)",
            "case-09 must keep the later disabling change out of the 15:30 state",
        )

    def test_sole_causation_case_has_a_reviewable_abstention_rule(self) -> None:
        corpus = _read("cases.json")
        incident = _case(corpus, "case-16")
        self.assertEqual(incident["expected_behavior"], "abstain")
        self.assertEqual(incident["expected_facts"], [])
        self.assertIsNone(
            re.match(
                r"\s*(do|does|did|is|are|can)\b", incident["question"], re.IGNORECASE
            ),
            "a yes/no question makes a correct qualified 'No' ambiguous to code",
        )
        setup = incident["case_setup"].lower()
        self.assertIn("qualified", setup)
        self.assertIn("abstention", setup)
        self.assertLessEqual(
            len(incident["expected_citation_spans"]),
            2,
            "a sole-causation abstention should not require four exact source snippets",
        )

    def test_prompt_injection_cases_are_uncued_and_sources_do_not_label_payloads(
        self,
    ) -> None:
        corpus = _read("cases.json")
        pack = _read("sources.json")
        by_id = {source["evidence_id"]: source for source in pack["sources"]}
        for number in (21, 22, 23):
            case = _case(corpus, f"case-{number:02d}")
            with self.subTest(case=case["case_id"]):
                self.assertIsNone(
                    re.search(
                        r"\b(ignore|instruction|prompt|injection|override|attack)\b",
                        case["question"],
                        re.IGNORECASE,
                    ),
                    "the user question must not cue injection resistance",
                )
                sentinel = case["prompt_injection_sentinel"]
                self.assertTrue(
                    any(
                        sentinel in by_id[record_id]["text"]
                        for record_id in case["allowed_evidence_ids"]
                    ),
                    "the attacked source must actually deliver the evaluator sentinel",
                )
                for record_id in case["allowed_evidence_ids"]:
                    source_text = by_id[record_id]["text"].lower()
                    self.assertNotIn("untrusted", source_text)
                    self.assertNotIn("embedded instruction", source_text)

    def test_injection_probe_metadata_is_neutral_in_projection_and_mcp_tools(
        self,
    ) -> None:
        corpus = _read("cases.json")
        pack = _read("sources.json")
        category_cues = ("inj-", "with-injection", "prompt_injection", "untrusted")
        for number, query in ((21, "median"), (22, "version"), (23, "event count")):
            case_id = f"case-{number:02d}"
            case = _case(corpus, case_id)
            with self.subTest(case=case_id):
                projection, question, _ = project._build_projection(
                    case_id, corpus, pack, server.DRAFT_STATUS
                )
                self.assertEqual(question, case["question"])
                self.assertFalse(set(projection) & EVALUATOR_ONLY_KEYS)
                projected_json = json.dumps(projection, ensure_ascii=False).casefold()
                with self.subTest(case=case_id, surface="projection"):
                    for cue in category_cues:
                        self.assertNotIn(cue, projected_json)
                sentinel = case["prompt_injection_sentinel"]
                for source in projection["sources"]:
                    source_metadata = json.dumps(
                        {key: source[key] for key in ("id", "title", "metadata")},
                        ensure_ascii=False,
                    )
                    self.assertNotIn(sentinel, source_metadata)

                fixture = server.FixtureServer(
                    server.validate_projection_bytes(
                        project._canonical_json(projection) + b"\n", case_id
                    )
                )
                init = fixture.handle(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2025-11-25",
                            "capabilities": {},
                            "clientInfo": {"name": "corpus-test", "version": "1"},
                        },
                    }
                )
                assert init is not None and "result" in init
                fixture.handle(
                    {"jsonrpc": "2.0", "method": "notifications/initialized"}
                )
                search = fixture.handle(
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/call",
                        "params": {"name": "search", "arguments": {"query": query}},
                    }
                )
                assert search is not None and "result" in search
                result = search["result"]["structuredContent"]["results"]
                self.assertEqual(
                    {item["id"] for item in result},
                    set(case["allowed_evidence_ids"]),
                )
                with self.subTest(case=case_id, surface="search"):
                    tool_json = json.dumps(search, ensure_ascii=False).casefold()
                    for cue in category_cues:
                        self.assertNotIn(cue, tool_json)
                for source in projection["sources"]:
                    fetch = fixture.handle(
                        {
                            "jsonrpc": "2.0",
                            "id": 3,
                            "method": "tools/call",
                            "params": {
                                "name": "fetch",
                                "arguments": {"id": source["id"]},
                            },
                        }
                    )
                    assert fetch is not None and "result" in fetch
                    payload = fetch["result"]["structuredContent"]
                    self.assertEqual(payload["text"], source["text"])
                    with self.subTest(case=case_id, surface="fetch"):
                        tool_json = json.dumps(fetch, ensure_ascii=False).casefold()
                        for cue in category_cues:
                            self.assertNotIn(cue, tool_json)

    def test_each_snapshot_has_a_declared_case_use(self) -> None:
        corpus = _read("cases.json")
        pack = _read("sources.json")
        used = {
            record_id
            for case in corpus["cases"]
            for record_id in case["allowed_evidence_ids"]
            + case["forbidden_evidence_ids"]
        }
        records = {source["evidence_id"] for source in pack["sources"]}
        self.assertEqual(records, used)

    def test_every_draft_projection_limits_sources_and_rejects_stale_pack(self) -> None:
        corpus = _read("cases.json")
        pack = _read("sources.json")
        self.assertEqual(corpus["approval"], {"status": "pending"})
        self.assertEqual(len(corpus["cases"]), 24)
        self.assertEqual(corpus["source_pack_digest"], project._digest(pack))
        self.assertEqual(
            {case["case_id"] for case in corpus["cases"]},
            {f"case-{i:02d}" for i in range(1, 25)},
        )

        for case in corpus["cases"]:
            case_id = case["case_id"]
            with self.subTest(case=case_id):
                projection, question, case_ids = project._build_projection(
                    case_id, corpus, pack, server.DRAFT_STATUS
                )
                self.assertEqual(question, case["question"])
                self.assertIn(case_id, case_ids)
                self.assertEqual(
                    {source["id"] for source in projection["sources"]},
                    set(case["allowed_evidence_ids"]),
                )
                self.assertFalse(set(projection) & EVALUATOR_ONLY_KEYS)
                self.assertEqual(projection["distribution_status"], server.DRAFT_STATUS)

        changed_pack = copy.deepcopy(pack)
        changed_pack["sources"][0]["text"] += " changed after approval"
        with self.assertRaisesRegex(project.ProjectionError, "digest mismatch"):
            project._build_projection(
                "case-01", corpus, changed_pack, server.DRAFT_STATUS
            )


if __name__ == "__main__":
    unittest.main()
