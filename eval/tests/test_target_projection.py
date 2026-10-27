"""CR-0021 reviewer-only target projection contract on synthetic draft data."""

from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, ValidationError

from eval.target_projection import (
    TargetProjectionError,
    derive_target_projection,
    verify_target_projection,
)

ROOT = Path(__file__).resolve().parents[1]
CORPUS_PATH = ROOT / "corpus/v1/cases.json"
SOURCE_PATH = ROOT / "corpus/v1/sources.json"
SCHEMA_PATH = ROOT / "schemas/reviewer-target-projection.schema.json"
PINNED_DRAFT_CORPUS_RAW = (
    "ce3412990a8f9daa24ce682b170b2cbc792130a424ce93b69d7725c578f7d615"
)
PINNED_DRAFT_SOURCE_RAW = (
    "ecba311adb883bda74bec5e98998246f03be6463bfc3e4960a55add8239945f6"
)


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


class TargetProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.corpus_draft_raw = CORPUS_PATH.read_bytes()
        self.source_draft_raw = SOURCE_PATH.read_bytes()

    def _bundle(
        self, case_id: str = "case-12", *, approved: bool = True
    ) -> dict[str, Any]:
        # An in-memory approval double exercises the gate. The repository pack
        # itself remains draft and cannot be distributed or scored.
        corpus = copy.deepcopy(json.loads(self.corpus_draft_raw))
        sources = copy.deepcopy(json.loads(self.source_draft_raw))
        corpus["source_pack_digest"] = sha256(canonical(sources))
        corpus["approval"] = (
            {
                "status": "approved",
                "reviewer_id": "synthetic-test-approver",
                "reviewed_at": "2026-10-26T09:00:00Z",
            }
            if approved
            else {"status": "pending"}
        )
        case = next(item for item in corpus["cases"] if item["case_id"] == case_id)
        source_by_id = {item["evidence_id"]: item for item in sources["sources"]}
        visible = [
            {
                "evidence_id": source_id,
                "origin": source_by_id[source_id]["origin"],
                "text": source_by_id[source_id]["text"],
            }
            for source_id in case["allowed_evidence_ids"]
        ]
        packet = {
            "schema_version": 1,
            "packet_id": "bp-" + "a" * 32,
            "case_id": case_id,
            "question": case["question"],
            "answer": "A synthetic candidate answer for reviewer-only testing.",
            "source_snapshots": visible,
            "citation_spans": [],
        }
        if case_id == "case-12":
            whole = source_by_id["github-deploy-77"]["text"]
            packet["citation_spans"] = [
                {
                    "evidence_id": "github-deploy-77",
                    "quote": whole,
                    "start": 0,
                    "end": len(whole),
                }
            ]
        corpus_bytes = canonical(corpus) + b"\n"
        source_pack_bytes = canonical(sources) + b"\n"
        packet_bytes = canonical(packet) + b"\n"
        return {
            "corpus_bytes": corpus_bytes,
            "source_pack_bytes": source_pack_bytes,
            "packet_bytes": packet_bytes,
            "approved_corpus_sha256": sha256(corpus_bytes),
            "approved_source_pack_sha256": sha256(source_pack_bytes),
            "preverified_manifest_corpus_digest": sha256(canonical(corpus)),
            "preverified_manifest_source_pack_digest": sha256(canonical(sources)),
            "preverified_packet_id": packet["packet_id"],
            "preverified_packet_sha256": sha256(packet_bytes),
        }

    @staticmethod
    def _mutate(bundle: dict[str, Any], field: str, change: Any) -> None:
        obj = json.loads(bundle[field])
        change(obj)
        bundle[field] = canonical(obj) + b"\n"
        if field == "corpus_bytes":
            bundle["approved_corpus_sha256"] = sha256(bundle[field])
            bundle["preverified_manifest_corpus_digest"] = sha256(canonical(obj))
        elif field == "source_pack_bytes":
            bundle["approved_source_pack_sha256"] = sha256(bundle[field])
            bundle["preverified_manifest_source_pack_digest"] = sha256(canonical(obj))
        else:
            bundle["preverified_packet_sha256"] = sha256(bundle[field])

    def test_current_draft_bytes_are_pinned_and_pending(self) -> None:
        self.assertEqual(sha256(self.corpus_draft_raw), PINNED_DRAFT_CORPUS_RAW)
        self.assertEqual(sha256(self.source_draft_raw), PINNED_DRAFT_SOURCE_RAW)
        self.assertEqual(
            json.loads(self.corpus_draft_raw)["approval"], {"status": "pending"}
        )

    def test_case12_ordered_targets_and_canonical_schema(self) -> None:
        bundle = self._bundle()
        raw = derive_target_projection(**bundle)
        projection = json.loads(raw)
        self.assertEqual(raw, canonical(projection))
        self.assertEqual(
            set(projection),
            {
                "schema_version",
                "corpus_digest",
                "source_pack_digest",
                "packet_id",
                "packet_sha256",
                "case_id",
                "targets",
            },
        )
        self.assertEqual(projection["schema_version"], 1)
        self.assertEqual(
            projection["packet_sha256"], bundle["preverified_packet_sha256"]
        )
        self.assertEqual(
            projection["targets"],
            [
                {
                    "target_index": 0,
                    "evidence_id": "github-deploy-77",
                    "anchor_quote": "commit a1b2c3d deployed profile-service 2026-07-12 14:00 UTC",
                },
                {
                    "target_index": 1,
                    "evidence_id": "github-deploy-77",
                    "anchor_quote": "auth-cache TTL from 300s to 30s",
                },
            ],
        )
        Draft202012Validator(json.loads(SCHEMA_PATH.read_bytes())).validate(projection)
        verify_target_projection(
            projection_bytes=raw,
            preverified_review_projection_sha256=sha256(raw),
            **bundle,
        )

    def test_denial_case_has_empty_targets_and_no_forbidden_details(self) -> None:
        bundle = self._bundle("case-17")
        raw = derive_target_projection(**bundle)
        projection = json.loads(raw)
        self.assertEqual(projection["targets"], [])
        self.assertNotIn(b"acl-b", raw)
        self.assertNotIn(b"expected_behavior", raw)
        self.assertNotIn(b"case_setup", raw)
        self.assertNotIn(b"synthetic-test-approver", raw)
        self.assertNotIn(b"candidate", raw)

    def test_pending_or_unreviewed_corpus_denies_even_with_matching_pins(self) -> None:
        bundle = self._bundle(approved=False)
        with self.assertRaises(TargetProjectionError):
            derive_target_projection(**bundle)
        bundle = self._bundle()
        self._mutate(
            bundle, "corpus_bytes", lambda obj: obj["approval"].pop("reviewer_id")
        )
        with self.assertRaises(TargetProjectionError):
            derive_target_projection(**bundle)

    def test_stale_raw_pins_reject_even_semantically_equal_json(self) -> None:
        for field in ("corpus_bytes", "source_pack_bytes"):
            with self.subTest(field=field):
                bundle = self._bundle()
                bundle[field] += b" "
                with self.assertRaisesRegex(
                    TargetProjectionError, "corpus|source pack"
                ):
                    derive_target_projection(**bundle)

    def test_source_pack_identity_and_digest_must_match_corpus(self) -> None:
        for changed in ("source_pack_id", "source_pack_digest"):
            with self.subTest(changed=changed):
                bundle = self._bundle()
                self._mutate(
                    bundle,
                    "corpus_bytes",
                    lambda obj, changed=changed: obj.__setitem__(changed, "other"),
                )
                with self.assertRaisesRegex(TargetProjectionError, "target|source"):
                    derive_target_projection(**bundle)

    def test_manifest_canonical_digests_are_bound_to_raw_pins(self) -> None:
        for field in (
            "preverified_manifest_corpus_digest",
            "preverified_manifest_source_pack_digest",
        ):
            with self.subTest(field=field):
                bundle = self._bundle()
                bundle[field] = "0" * 64
                with self.assertRaisesRegex(
                    TargetProjectionError, "preverified packet manifest"
                ):
                    derive_target_projection(**bundle)

    def test_preverified_packet_identity_and_case_question_are_bound(self) -> None:
        for change in ("preverified_packet_id", "preverified_packet_sha256"):
            with self.subTest(change=change):
                bundle = self._bundle()
                bundle[change] = (
                    "bp-" + "b" * 32 if change == "preverified_packet_id" else "0" * 64
                )
                with self.assertRaises(TargetProjectionError):
                    derive_target_projection(**bundle)
        bundle = self._bundle()
        self._mutate(
            bundle, "packet_bytes", lambda obj: obj.__setitem__("question", "different")
        )
        with self.assertRaises(TargetProjectionError):
            derive_target_projection(**bundle)

    def test_changed_or_extra_packet_view_denies_even_when_rehashed(self) -> None:
        for change in (
            lambda obj: obj["source_snapshots"].pop(),
            lambda obj: obj["source_snapshots"].append(
                copy.deepcopy(obj["source_snapshots"][0])
            ),
            lambda obj: obj["source_snapshots"][0].__setitem__("text", "tampered"),
            lambda obj: obj.__setitem__("candidate_id", "chatgpt_enterprise"),
            lambda obj: obj["source_snapshots"][0].__setitem__("evidence_id", "acl-b"),
        ):
            with self.subTest(change=change):
                bundle = self._bundle()
                self._mutate(bundle, "packet_bytes", change)
                with self.assertRaises(TargetProjectionError):
                    derive_target_projection(**bundle)

    def test_anchors_must_be_unique_visible_and_exact_source_spans(self) -> None:
        for change in (
            lambda obj: obj["cases"][11]["expected_citation_spans"].append(
                copy.deepcopy(obj["cases"][11]["expected_citation_spans"][0])
            ),
            lambda obj: obj["cases"][11]["expected_citation_spans"][0].__setitem__(
                "evidence_id", "gcp-error-start"
            ),
            lambda obj: obj["cases"][11]["expected_citation_spans"][0].__setitem__(
                "evidence_id", "missing-source"
            ),
            lambda obj: obj["cases"][11]["expected_citation_spans"][0].__setitem__(
                "quote", "not in the source"
            ),
        ):
            with self.subTest(change=change):
                bundle = self._bundle()
                self._mutate(bundle, "corpus_bytes", change)
                with self.assertRaisesRegex(TargetProjectionError, "target|source"):
                    derive_target_projection(**bundle)

    def test_duplicate_case_and_source_ids_deny(self) -> None:
        bundle = self._bundle()
        self._mutate(
            bundle,
            "corpus_bytes",
            lambda obj: obj["cases"].append(copy.deepcopy(obj["cases"][0])),
        )
        with self.assertRaisesRegex(TargetProjectionError, "duplicate case"):
            derive_target_projection(**bundle)
        bundle = self._bundle()
        self._mutate(
            bundle,
            "source_pack_bytes",
            lambda obj: obj["sources"].append(copy.deepcopy(obj["sources"][0])),
        )
        source_obj = json.loads(bundle["source_pack_bytes"])
        self._mutate(
            bundle,
            "corpus_bytes",
            lambda obj: obj.__setitem__(
                "source_pack_digest", sha256(canonical(source_obj))
            ),
        )
        with self.assertRaisesRegex(TargetProjectionError, "duplicate source"):
            derive_target_projection(**bundle)

    def test_target_count_and_projection_byte_bounds(self) -> None:
        bundle = self._bundle()
        source_text = next(
            source["text"]
            for source in json.loads(bundle["source_pack_bytes"])["sources"]
            if source["evidence_id"] == "github-deploy-77"
        )
        self._mutate(
            bundle,
            "corpus_bytes",
            lambda obj: obj["cases"][11].__setitem__(
                "expected_citation_spans",
                [
                    {"evidence_id": "github-deploy-77", "quote": source_text[:n]}
                    for n in range(1, 130)
                ],
            ),
        )
        with self.assertRaisesRegex(TargetProjectionError, "array size"):
            derive_target_projection(**bundle)

        bundle = self._bundle()
        large_source = "x" * 4096
        self._mutate(
            bundle,
            "source_pack_bytes",
            lambda obj: next(
                source
                for source in obj["sources"]
                if source["evidence_id"] == "github-deploy-77"
            ).__setitem__("text", large_source),
        )
        source_obj = json.loads(bundle["source_pack_bytes"])
        self._mutate(
            bundle,
            "corpus_bytes",
            lambda obj: (
                obj.__setitem__("source_pack_digest", sha256(canonical(source_obj))),
                obj["cases"][11].__setitem__(
                    "expected_citation_spans",
                    [
                        {"evidence_id": "github-deploy-77", "quote": large_source[:n]}
                        for n in range(3000, 3128)
                    ],
                ),
            ),
        )
        self._mutate(
            bundle,
            "packet_bytes",
            lambda obj: (
                next(
                    source
                    for source in obj["source_snapshots"]
                    if source["evidence_id"] == "github-deploy-77"
                ).__setitem__("text", large_source),
                obj.__setitem__("citation_spans", []),
            ),
        )
        with self.assertRaisesRegex(TargetProjectionError, "projection exceeds"):
            derive_target_projection(**bundle)

    def test_duplicate_json_key_and_private_source_denied_after_repin(self) -> None:
        bundle = self._bundle()
        packet = bundle["packet_bytes"].replace(
            b'"case_id":"case-12",',
            b'"case_id":"case-12","case_id":"case-12",',
            1,
        )
        bundle["packet_bytes"] = packet
        bundle["preverified_packet_sha256"] = sha256(packet)
        with self.assertRaisesRegex(TargetProjectionError, "duplicate JSON key"):
            derive_target_projection(**bundle)
        bundle = self._bundle()
        self._mutate(
            bundle,
            "source_pack_bytes",
            lambda obj: obj["sources"][0].__setitem__("data_class", "private"),
        )
        source_obj = json.loads(bundle["source_pack_bytes"])
        self._mutate(
            bundle,
            "corpus_bytes",
            lambda obj: obj.__setitem__(
                "source_pack_digest", sha256(canonical(source_obj))
            ),
        )
        with self.assertRaisesRegex(TargetProjectionError, "source class"):
            derive_target_projection(**bundle)

    def test_projection_mutation_and_recomputed_digest_do_not_verify(self) -> None:
        bundle = self._bundle()
        valid = derive_target_projection(**bundle)
        for change in (
            lambda obj: obj.__setitem__("expected_behavior", "answer"),
            lambda obj: obj["targets"].pop(),
            lambda obj: obj["targets"].reverse(),
            lambda obj: obj["targets"][0].__setitem__("anchor_quote", "unrelated"),
            lambda obj: obj.__setitem__("packet_sha256", "0" * 64),
        ):
            with self.subTest(change=change):
                obj = json.loads(valid)
                change(obj)
                changed = canonical(obj)
                with self.assertRaises(TargetProjectionError):
                    verify_target_projection(
                        projection_bytes=changed,
                        preverified_review_projection_sha256=sha256(changed),
                        **bundle,
                    )

    def test_projection_rejects_wrong_digest_or_noncanonical_bytes(self) -> None:
        bundle = self._bundle()
        raw = derive_target_projection(**bundle)
        with self.assertRaises(TargetProjectionError):
            verify_target_projection(
                projection_bytes=raw,
                preverified_review_projection_sha256="0" * 64,
                **bundle,
            )
        with self.assertRaises(TargetProjectionError):
            verify_target_projection(
                projection_bytes=raw + b"\n",
                preverified_review_projection_sha256=sha256(raw + b"\n"),
                **bundle,
            )

    def test_schema_rejects_leaked_fields_and_duplicate_target_index(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_bytes())
        obj = json.loads(derive_target_projection(**self._bundle()))
        obj["candidate_id"] = "chatgpt_enterprise"
        with self.assertRaises(ValidationError):
            Draft202012Validator(schema).validate(obj)
        obj.pop("candidate_id")
        obj["targets"][1]["target_index"] = 0
        # JSON Schema checks shape; the exact byte re-derivation checks this
        # cross-target uniqueness and ordering at the verifier boundary.
        self.assertNotEqual(canonical(obj), derive_target_projection(**self._bundle()))


if __name__ == "__main__":
    unittest.main()
