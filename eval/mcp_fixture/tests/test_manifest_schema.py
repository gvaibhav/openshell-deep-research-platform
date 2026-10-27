"""Schema checks for the independently pinned synthetic tester manifest."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator, ValidationError

from scripts import validate_repo

ROOT = Path(__file__).resolve().parents[3]
MANIFEST_SCHEMA = ROOT / "eval/mcp_fixture/approval-manifest.schema.json"


def _approved_manifest() -> dict:
    digest = "a" * 64
    return {
        "schema_version": 1,
        "approval": {
            "status": "approved",
            "reviewer_id": "synthetic-test-reviewer",
            "reviewed_at": "2026-10-26T00:00:00Z",
            "approval_ref": "synthetic-test-only",
        },
        "data_use_destination": "chatgpt_enterprise",
        "corpus_sha256": digest,
        "sources_sha256": digest,
        "rubric_sha256": digest,
        "cases": [
            {
                "case_id": f"case-{number:02d}",
                "question_sha256": digest,
                "projection_sha256": digest,
            }
            for number in range(1, 25)
        ],
    }


class ManifestSchemaTests(unittest.TestCase):
    def test_schema_accepts_exact_24_case_ids(self) -> None:
        schema = json.loads(MANIFEST_SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(_approved_manifest())

    def test_schema_rejects_duplicate_case_id_even_with_distinct_hashes(self) -> None:
        schema = json.loads(MANIFEST_SCHEMA.read_text(encoding="utf-8"))
        manifest = _approved_manifest()
        manifest["cases"][-1] = {
            "case_id": "case-01",
            "question_sha256": "b" * 64,
            "projection_sha256": "c" * 64,
        }
        with self.assertRaises(ValidationError):
            Draft202012Validator(schema).validate(manifest)

    def test_repo_schema_gate_discovers_eval_directories(self) -> None:
        paths = set(validate_repo.repository_schema_paths())
        for directory in (
            ROOT / "contracts",
            ROOT / "eval" / "schemas",
            ROOT / "eval" / "mcp_fixture",
        ):
            with self.subTest(directory=directory):
                self.assertTrue(set(directory.glob("*.schema.json")) <= paths)
        self.assertIn(ROOT / "eval/schemas/scorecard.schema.json", paths)
        self.assertIn(MANIFEST_SCHEMA, paths)

    def test_repo_schema_gate_rejects_malformed_eval_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fake_eval_schemas = Path(directory) / "eval" / "schemas"
            fake_eval_schemas.mkdir(parents=True)
            bad_schema = fake_eval_schemas / "invalid.schema.json"
            bad_schema.write_text(
                json.dumps(
                    {
                        "$schema": "https://json-schema.org/draft/2020-12/schema",
                        "$id": "https://schemas.example.invalid/invalid.schema.json",
                        "type": "not-a-json-schema-type",
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(validate_repo, "SCHEMA_DIRS", (fake_eval_schemas,)):
                errors: list[str] = []
                validate_repo.load_repository_schemas(errors)
            self.assertEqual(len(errors), 1)
            self.assertIn("invalid.schema.json", errors[0])
            self.assertIn("not-a-json-schema-type", errors[0])


if __name__ == "__main__":
    unittest.main()
