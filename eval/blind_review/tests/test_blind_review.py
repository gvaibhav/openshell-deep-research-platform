"""Blind packet boundary tests for synthetic matched research observations."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from eval.blind_review import tool as blind_tool_module
from eval.blind_review.tool import BlindReviewError, prepare_packets, verify_and_unblind

EVAL_ROOT = Path(__file__).resolve().parents[2]
OPENSSL_BIN = "/usr/bin/openssl" if Path("/usr/bin/openssl").is_file() else None


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


class BlindReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        # Test-only pin: ownership, real signature checks and digest denial still run.
        self.enterContext(
            patch.object(
                blind_tool_module,
                "TRUSTED_VERIFIER_SHA256",
                file_hash(Path("/usr/bin/openssl")),
            )
        )
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve(strict=True)
        self.cases = json.loads(
            (EVAL_ROOT / "corpus/v1/cases.json").read_text(encoding="utf-8")
        )
        self.sources = json.loads(
            (EVAL_ROOT / "corpus/v1/sources.json").read_text(encoding="utf-8")
        )
        self.rubric = json.loads(
            (EVAL_ROOT / "corpus/v1/rubric.json").read_text(encoding="utf-8")
        )
        self.cases["source_pack_digest"] = digest(self.sources)
        self.case = next(
            case for case in self.cases["cases"] if case["case_id"] == "case-01"
        )
        self.source_by_id = {
            source["evidence_id"]: source for source in self.sources["sources"]
        }
        text = self.source_by_id["pub-launch-final"]["text"]
        quote = "opened to users on 2026-04-14"
        start = text.index(quote)
        self.answer = "The fictional Atlas beta opened on 2026-04-14."
        self.observation: dict[str, Any] = {
            "status": "completed",
            "case_id": "case-01",
            "candidate_id": "chatgpt_enterprise",
            "run_id": "run-chatgpt-01",
            "candidate_version": "sensitive-candidate-version-canary",
            "model_version": "sensitive-model-version-canary",
            "source_delivery": "sensitive-delivery-canary",
            "answer_artifact_ref": "artifact:raw-chatgpt-01",
            "latency_ms": 123,
            "cost_usd": 0.01,
            "user_effort_minutes": 2,
            "raw_answer": self.answer,
            "packet_answer": self.answer,
            "screening": {
                "custodian_id": "screening-custodian",
                "screened_at": "2026-10-26T10:00:00Z",
                "record_ref": "artifact:screening-01",
                "raw_answer_sha256": hashlib.sha256(self.answer.encode()).hexdigest(),
                "packet_answer_sha256": hashlib.sha256(
                    self.answer.encode()
                ).hexdigest(),
            },
            "citations": [
                {
                    "evidence_id": "pub-launch-final",
                    "quote": quote,
                    "start": start,
                    "end": start + len(quote),
                }
            ],
        }
        self.cases_path = self.root / "cases.json"
        self.sources_path = self.root / "sources.json"
        self.rubric_path = self.root / "rubric.json"
        self.observations_path = self.root / "observations.json"
        self.packet_dir = self.root / "reviewer-packets"
        self.map_path = self.root / "custodian" / "candidate-map.json"
        self.reviews_path = self.root / "reviews.json"
        self.receipt_path = self.root / "receipt.json"
        self.signature_path = self.root / "receipt.sig"
        self.public_key_path = self.root / "witness-public.pem"
        self.private_key_path = self.root / "witness-private.pem"
        self.unblinded_path = self.root / "custodian" / "unblinded.json"
        self._write_inputs(approved=True)

    def _write_inputs(self, *, approved: bool) -> None:
        self.cases["approval"] = (
            {
                "status": "approved",
                "reviewer_id": "corpus-reviewer",
                "reviewed_at": "2026-10-26T09:00:00Z",
            }
            if approved
            else {"status": "pending"}
        )
        self.rubric["approval"] = (
            {
                "status": "approved",
                "reviewer_id": "rubric-reviewer",
                "reviewed_at": "2026-10-26T09:00:00Z",
            }
            if approved
            else {"status": "pending"}
        )
        save(self.cases_path, self.cases)
        save(self.sources_path, self.sources)
        save(self.rubric_path, self.rubric)
        self._write_observations([self.observation])

    def _write_observations(self, observations: list[dict[str, Any]]) -> None:
        save(
            self.observations_path,
            {
                "schema_version": 2,
                "cell_count": len(observations),
                "corpus_digest": digest(self.cases),
                "source_pack_digest": digest(self.sources),
                "rubric_digest": digest(self.rubric),
                "observations": observations,
            },
        )

    def _prepare(self) -> dict[str, Any]:
        return prepare_packets(
            corpus_path=self.cases_path,
            sources_path=self.sources_path,
            rubric_path=self.rubric_path,
            observations_path=self.observations_path,
            packet_dir=self.packet_dir,
            map_path=self.map_path,
        )

    def _prepare_reviews(self) -> tuple[dict[str, Any], dict[str, Any]]:
        manifest = self._prepare()
        public_manifest_path = self.packet_dir / "packet-manifest.json"
        case_by_id = {case["case_id"]: case for case in self.cases["cases"]}
        review_entries = []
        for record in manifest["packets"]:
            packet_path = self.packet_dir / f"{record['packet_id']}.json"
            packet = json.loads(packet_path.read_text(encoding="utf-8"))
            dimensions = case_by_id[packet["case_id"]]["rubric_dimensions"]
            review_entries.append(
                {
                    "packet_id": record["packet_id"],
                    "packet_sha256": record["packet_sha256"],
                    "reviewer_id": "blind-human-1",
                    "reviewed_at": "2026-10-26T11:00:00Z",
                    "scores": {dimension: 4 for dimension in dimensions},
                    "notes": "Supported by visible snapshot.",
                }
            )
        reviews = {
            "schema_version": 1,
            "packet_manifest_sha256": file_hash(public_manifest_path),
            "reviews": review_entries,
        }
        save(self.reviews_path, reviews)
        receipt = {
            "schema_version": 1,
            "packet_manifest_sha256": file_hash(public_manifest_path),
            "candidate_map_sha256": file_hash(self.map_path),
            "reviews_sha256": file_hash(self.reviews_path),
            "witness_id": "independent-freeze-witness",
            "witnessed_at": "2026-10-26T12:00:00Z",
        }
        save(self.receipt_path, receipt)
        return manifest, reviews

    def _sign_receipt(self) -> str:
        assert OPENSSL_BIN is not None
        subprocess.run(
            [
                OPENSSL_BIN,
                "genpkey",
                "-algorithm",
                "RSA",
                "-pkeyopt",
                "rsa_keygen_bits:2048",
                "-out",
                str(self.private_key_path),
            ],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                OPENSSL_BIN,
                "pkey",
                "-in",
                str(self.private_key_path),
                "-pubout",
                "-out",
                str(self.public_key_path),
            ],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                OPENSSL_BIN,
                "dgst",
                "-sha256",
                "-sign",
                str(self.private_key_path),
                "-out",
                str(self.signature_path),
                str(self.receipt_path),
            ],
            check=True,
            capture_output=True,
        )
        return file_hash(self.public_key_path)

    def _unblind(self, trusted_key_sha256: str) -> dict[str, Any]:
        assert OPENSSL_BIN is not None
        return verify_and_unblind(
            corpus_path=self.cases_path,
            sources_path=self.sources_path,
            rubric_path=self.rubric_path,
            raw_observations_path=self.observations_path,
            packet_dir=self.packet_dir,
            map_path=self.map_path,
            reviews_path=self.reviews_path,
            receipt_path=self.receipt_path,
            signature_path=self.signature_path,
            public_key_path=self.public_key_path,
            trusted_key_sha256=trusted_key_sha256,
            expected_witness_id="independent-freeze-witness",
            control_review_path=self.root / "legacy-no-control-review.json",
            control_signature_path=self.root / "legacy-no-control-review.sig",
            control_public_key_path=self.root / "legacy-no-control-key.pem",
            trusted_control_key_sha256="0" * 64,
            expected_control_reviewer_id="legacy-missing-control-reviewer",
            output_path=self.unblinded_path,
        )

    def _resign_changed_packet(self, field: str) -> str:
        manifest, reviews = self._prepare_reviews()
        key_hash = self._sign_receipt()
        packet_path = self.packet_dir / f"{manifest['packets'][0]['packet_id']}.json"
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        if field == "question":
            packet["question"] = (
                "A substituted question unrelated to the approved case."
            )
        elif field == "source_text":
            packet["source_snapshots"][0]["text"] += " TAMPERED SOURCE VIEW"
        elif field == "answer_identity":
            packet["answer"] += " chatgpt_enterprise"
        else:
            self.fail("unsupported test change")
        save(packet_path, packet)
        packet_hash = file_hash(packet_path)
        manifest["packets"][0]["packet_sha256"] = packet_hash
        save(self.packet_dir / "packet-manifest.json", manifest)
        manifest_hash = file_hash(self.packet_dir / "packet-manifest.json")
        concealed = json.loads(self.map_path.read_text(encoding="utf-8"))
        concealed["packet_manifest_sha256"] = manifest_hash
        concealed["assignments"][0]["packet_sha256"] = packet_hash
        if field == "answer_identity":
            concealed["assignments"][0]["screening"]["packet_answer_sha256"] = (
                hashlib.sha256(packet["answer"].encode()).hexdigest()
            )
        save(self.map_path, concealed)
        reviews["packet_manifest_sha256"] = manifest_hash
        reviews["reviews"][0]["packet_sha256"] = packet_hash
        save(self.reviews_path, reviews)
        receipt = json.loads(self.receipt_path.read_text(encoding="utf-8"))
        receipt["packet_manifest_sha256"] = manifest_hash
        receipt["candidate_map_sha256"] = file_hash(self.map_path)
        receipt["reviews_sha256"] = file_hash(self.reviews_path)
        save(self.receipt_path, receipt)
        assert OPENSSL_BIN is not None
        subprocess.run(
            [
                OPENSSL_BIN,
                "dgst",
                "-sha256",
                "-sign",
                str(self.private_key_path),
                "-out",
                str(self.signature_path),
                str(self.receipt_path),
            ],
            check=True,
            capture_output=True,
        )
        return key_hash

    def test_pending_corpus_or_rubric_cannot_make_packets(self) -> None:
        self._write_inputs(approved=False)
        with self.assertRaises(BlindReviewError):
            self._prepare()
        self.assertFalse(self.packet_dir.exists())
        self.assertFalse(self.map_path.exists())

        self._write_inputs(approved=True)
        self.rubric["approval"] = {"status": "pending"}
        save(self.rubric_path, self.rubric)
        self._write_observations([self.observation])
        with self.assertRaises(BlindReviewError):
            self._prepare()
        self.assertFalse(self.packet_dir.exists())

    def test_shared_preflight_denies_repinned_incomplete_case_dimensions(self) -> None:
        self.case["rubric_dimensions"] = ["factual_accuracy"]
        self._write_inputs(approved=True)
        with self.assertRaises(BlindReviewError):
            self._prepare()
        self.assertFalse(self.packet_dir.exists())
        self.assertFalse(self.map_path.exists())

    def test_packets_are_random_anonymous_and_map_is_separate_private(self) -> None:
        second = copy.deepcopy(self.observation)
        second["candidate_id"] = "restricted_worker"
        second["run_id"] = "run-restricted-01"
        second["candidate_version"] = "second-version-canary"
        second["model_version"] = "second-model-canary"
        self._write_observations([self.observation, second])

        manifest = self._prepare()
        self.assertEqual(manifest["packet_count"], 2)
        self.assertEqual(stat.S_IMODE(self.map_path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.packet_dir.stat().st_mode), 0o700)
        self.assertFalse(self.map_path.is_relative_to(self.packet_dir))
        map_data = json.loads(self.map_path.read_text(encoding="utf-8"))
        self.assertEqual(len(map_data["assignments"]), 2)

        for record in manifest["packets"]:
            self.assertRegex(record["packet_id"], r"^bp-[0-9a-f]{32}$")
            packet_path = self.packet_dir / f"{record['packet_id']}.json"
            packet = json.loads(packet_path.read_text(encoding="utf-8"))
            self.assertEqual(
                set(packet),
                {
                    "schema_version",
                    "packet_id",
                    "case_id",
                    "question",
                    "answer",
                    "source_snapshots",
                    "citation_spans",
                },
            )
            self.assertEqual(packet["answer"], self.answer)
            self.assertEqual(
                [source["evidence_id"] for source in packet["source_snapshots"]],
                self.case["allowed_evidence_ids"],
            )
            self.assertEqual(file_hash(packet_path), record["packet_sha256"])
            wire = packet_path.read_text(encoding="utf-8")
            for marker in (
                "chatgpt_enterprise",
                "restricted_worker",
                "run-chatgpt-01",
                "sensitive-candidate-version-canary",
                "sensitive-model-version-canary",
                "sensitive-delivery-canary",
                "expected_facts",
                "expected_citation_spans",
                "forbidden_evidence_ids",
            ):
                self.assertNotIn(marker, wire)

        second_dir = self.root / "reviewer-packets-second"
        second_map = self.root / "custodian" / "candidate-map-second.json"
        manifest_2 = prepare_packets(
            corpus_path=self.cases_path,
            sources_path=self.sources_path,
            rubric_path=self.rubric_path,
            observations_path=self.observations_path,
            packet_dir=second_dir,
            map_path=second_map,
        )
        self.assertTrue(
            {x["packet_id"] for x in manifest["packets"]}.isdisjoint(
                {x["packet_id"] for x in manifest_2["packets"]}
            )
        )

    def test_denies_wrong_digests_forbidden_citation_and_source_text(self) -> None:
        observations = json.loads(self.observations_path.read_text(encoding="utf-8"))
        observations["source_pack_digest"] = "0" * 64
        save(self.observations_path, observations)
        with self.assertRaises(BlindReviewError):
            self._prepare()
        self.assertFalse(self.packet_dir.exists())

        forbidden_case = next(
            case for case in self.cases["cases"] if case["forbidden_evidence_ids"]
        )
        record = copy.deepcopy(self.observation)
        record["case_id"] = forbidden_case["case_id"]
        record["citations"] = [
            {
                "evidence_id": forbidden_case["forbidden_evidence_ids"][0],
                "quote": "x",
                "start": 0,
                "end": 1,
            }
        ]
        self._write_observations([record])
        with self.assertRaises(BlindReviewError):
            self._prepare()
        self.assertFalse(self.packet_dir.exists())

        forbidden_text = self.source_by_id[forbidden_case["forbidden_evidence_ids"][0]][
            "text"
        ]
        record["citations"] = []
        record["packet_answer"] = forbidden_text
        record["screening"]["packet_answer_sha256"] = hashlib.sha256(
            forbidden_text.encode()
        ).hexdigest()
        self._write_observations([record])
        with self.assertRaises(BlindReviewError):
            self._prepare()
        self.assertFalse(self.packet_dir.exists())

    def test_denies_duplicate_runs_bad_spans_and_self_identification(self) -> None:
        second = copy.deepcopy(self.observation)
        self._write_observations([self.observation, second])
        with self.assertRaises(BlindReviewError):
            self._prepare()

        bad = copy.deepcopy(self.observation)
        bad["citations"][0]["start"] += 1
        self._write_observations([bad])
        with self.assertRaises(BlindReviewError):
            self._prepare()

        bad = copy.deepcopy(self.observation)
        bad["packet_answer"] += " chatgpt_enterprise"
        bad["screening"]["packet_answer_sha256"] = hashlib.sha256(
            bad["packet_answer"].encode()
        ).hexdigest()
        self._write_observations([bad])
        with self.assertRaises(BlindReviewError):
            self._prepare()

    def test_preparation_denies_consistently_hashed_answer_replacement(self) -> None:
        wrong = copy.deepcopy(self.observation)
        wrong["raw_answer"] = "The fictional Atlas beta opened on 2026-05-01."
        wrong["screening"]["raw_answer_sha256"] = hashlib.sha256(
            wrong["raw_answer"].encode("utf-8")
        ).hexdigest()
        self._write_observations([wrong])
        with self.assertRaises(BlindReviewError):
            self._prepare()
        self.assertFalse(self.packet_dir.exists())
        self.assertFalse(self.map_path.exists())

    def test_preparation_denies_unicode_normalization_answer_change(self) -> None:
        changed = copy.deepcopy(self.observation)
        changed["raw_answer"] = "Caf\u00e9 was included in the synthetic answer."
        changed["packet_answer"] = "Cafe\u0301 was included in the synthetic answer."
        changed["screening"]["raw_answer_sha256"] = hashlib.sha256(
            changed["raw_answer"].encode("utf-8")
        ).hexdigest()
        changed["screening"]["packet_answer_sha256"] = hashlib.sha256(
            changed["packet_answer"].encode("utf-8")
        ).hexdigest()
        self._write_observations([changed])
        with self.assertRaises(BlindReviewError):
            self._prepare()
        self.assertFalse(self.packet_dir.exists())

    def test_preparation_map_route_a_b_a_never_writes_labels_into_packets(self) -> None:
        reviewer_root = self.root / "reviewer-output"
        reviewer_root.mkdir()
        self.packet_dir = reviewer_root / "private"
        safe_root = self.root / "safe-output"
        safe_private = safe_root / "private"
        safe_private.mkdir(parents=True, mode=0o700)
        attacker = self.root / "attacker-output"
        attacker.mkdir()
        route = attacker / "route"
        route.symlink_to(safe_root, target_is_directory=True)
        self.map_path = route / "private" / "candidate-map.json"
        original_open = os.open
        switched = False

        def switch_before_map_create(
            path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
            flags: int,
            *args: Any,
            **kwargs: Any,
        ) -> int:
            nonlocal switched
            is_map_write = path == self.map_path or (
                isinstance(path, str)
                and path.startswith(".scorecard-")
                and flags & os.O_CREAT
            )
            if is_map_write and not switched:
                route.unlink()
                route.symlink_to(reviewer_root, target_is_directory=True)
                switched = True
                try:
                    return original_open(path, flags, *args, **kwargs)
                finally:
                    route.unlink()
                    route.symlink_to(safe_root, target_is_directory=True)
            return original_open(path, flags, *args, **kwargs)

        rejected = False
        with patch(
            "eval.blind_review.tool.os.open", side_effect=switch_before_map_create
        ):
            try:
                self._prepare()
            except BlindReviewError:
                rejected = True
        # The output route is rejected before this former publication hook runs.
        self.assertFalse(switched)
        self.assertFalse((self.packet_dir / "candidate-map.json").exists())
        self.assertFalse((safe_private / "candidate-map.json").exists())
        self.assertFalse(self.packet_dir.exists())
        self.assertEqual(list(safe_private.glob(".scorecard-*.tmp")), [])
        self.assertTrue(rejected)

    def test_preparation_pins_map_route_before_private_parent_creation(self) -> None:
        safe_root = self.root / "safe-map-root"
        old_review_root = self.root / "old-review-root"
        safe_root.mkdir()
        (old_review_root / "private").mkdir(parents=True, mode=0o700)
        selector = self.root / "map-selector"
        selector.symlink_to(safe_root, target_is_directory=True)
        self.map_path = selector / "private" / "candidate-map.json"
        original_private = blind_tool_module._private_directory
        switched = False

        def switch_after_private_parent(path: Path) -> None:
            nonlocal switched
            original_private(path)
            selector.unlink()
            selector.symlink_to(old_review_root, target_is_directory=True)
            switched = True

        try:
            with (
                patch(
                    "eval.blind_review.tool._private_directory",
                    side_effect=switch_after_private_parent,
                ),
                self.assertRaises(BlindReviewError),
            ):
                self._prepare()
            self.assertTrue(switched)
            self.assertFalse(
                (old_review_root / "private" / "candidate-map.json").exists()
            )
            self.assertFalse((safe_root / "private" / "candidate-map.json").exists())
            self.assertFalse(self.packet_dir.exists())
        finally:
            if selector.is_symlink():
                selector.unlink()
                selector.symlink_to(safe_root, target_is_directory=True)

    def test_preparation_denies_mkdir_to_open_packet_inode_swap(self) -> None:
        original_open = os.open
        retired_packets = self.root / "retired-packets"
        sentinel = self.packet_dir / "keep.txt"
        swapped = False

        def swap_new_packet_directory(
            path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
            flags: int,
            *args: Any,
            **kwargs: Any,
        ) -> int:
            nonlocal swapped
            if (
                not swapped
                and path == self.packet_dir.name
                and flags & os.O_DIRECTORY
                and kwargs.get("dir_fd") is not None
            ):
                self.packet_dir.rename(retired_packets)
                self.packet_dir.mkdir(mode=0o700)
                sentinel.write_text("foreign packet sentinel", encoding="utf-8")
                swapped = True
            return original_open(path, flags, *args, **kwargs)

        with (
            patch(
                "eval.blind_review.tool.os.open", side_effect=swap_new_packet_directory
            ),
            self.assertRaises(BlindReviewError),
        ):
            self._prepare()
        self.assertTrue(swapped)
        self.assertEqual(
            sentinel.read_text(encoding="utf-8"), "foreign packet sentinel"
        )
        self.assertEqual(
            sorted(path.name for path in self.packet_dir.iterdir()), ["keep.txt"]
        )
        self.assertFalse(self.map_path.exists())
        self.assertTrue(retired_packets.is_dir())

    def test_preparation_cleanup_never_deletes_switched_sentinel_tree(self) -> None:
        work_root = self.root / "work-output"
        work_root.mkdir()
        (work_root / "private").mkdir(mode=0o700)
        selector = self.root / "selector"
        selector.symlink_to(work_root, target_is_directory=True)
        self.packet_dir = selector / "private" / "packets"
        sentinel_root = self.root / "unrelated-sentinel"
        sentinel_packets = sentinel_root / "private" / "packets"
        sentinel_packets.mkdir(parents=True)
        sentinel = sentinel_packets / "keep.txt"
        sentinel.write_text("unrelated sentinel", encoding="utf-8")
        original_open = os.open
        switched = False

        def fail_map_create_after_selector_switch(
            path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
            flags: int,
            *args: Any,
            **kwargs: Any,
        ) -> int:
            nonlocal switched
            is_map_write = path == self.map_path or (
                isinstance(path, str)
                and path.startswith(".scorecard-")
                and flags & os.O_CREAT
            )
            if is_map_write and not switched:
                selector.unlink()
                selector.symlink_to(sentinel_root, target_is_directory=True)
                switched = True
                raise OSError("synthetic map publication failure")
            return original_open(path, flags, *args, **kwargs)

        try:
            with (
                patch(
                    "eval.blind_review.tool.os.open",
                    side_effect=fail_map_create_after_selector_switch,
                ),
                self.assertRaises(BlindReviewError),
            ):
                self._prepare()
            # A symlink packet route now fails before any artifact is created.
            self.assertFalse(switched)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "unrelated sentinel")
            self.assertFalse((work_root / "private" / "packets").exists())
            self.assertFalse(self.map_path.exists())
        finally:
            if selector.is_symlink():
                selector.unlink()
                selector.symlink_to(work_root, target_is_directory=True)

    def test_packet_write_uses_held_directory_after_ancestor_switch(self) -> None:
        work_root = self.root / "work-output"
        work_private = work_root / "private"
        work_private.mkdir(parents=True, mode=0o700)
        selector = self.root / "packet-route"
        selector.symlink_to(work_root, target_is_directory=True)
        self.packet_dir = selector / "private" / "packets"
        sentinel_root = self.root / "unrelated-sentinel"
        sentinel_packets = sentinel_root / "private" / "packets"
        sentinel_packets.mkdir(parents=True)
        sentinel = sentinel_packets / "keep.txt"
        sentinel.write_text("unrelated sentinel", encoding="utf-8")
        original_open = os.open
        switched = False

        def switch_before_packet_write(
            path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
            flags: int,
            *args: Any,
            **kwargs: Any,
        ) -> int:
            nonlocal switched
            if (
                not switched
                and isinstance(path, str)
                and path.startswith("bp-")
                and flags & os.O_CREAT
            ):
                selector.unlink()
                selector.symlink_to(sentinel_root, target_is_directory=True)
                switched = True
            return original_open(path, flags, *args, **kwargs)

        try:
            with (
                patch(
                    "eval.blind_review.tool.os.open",
                    side_effect=switch_before_packet_write,
                ),
                self.assertRaises(BlindReviewError),
            ):
                self._prepare()
            # No packet write is attempted through a symlink route.
            self.assertFalse(switched)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "unrelated sentinel")
            self.assertEqual(
                sorted(path.name for path in sentinel_packets.iterdir()), ["keep.txt"]
            )
            self.assertFalse((work_private / "packets").exists())
            self.assertFalse(self.map_path.exists())
        finally:
            if selector.is_symlink():
                selector.unlink()
                selector.symlink_to(work_root, target_is_directory=True)

    def test_packet_write_uses_held_directory_after_no_symlink_rename(self) -> None:
        retired_packets = self.root / "retired-created-packets"
        sentinel = self.packet_dir / "keep.txt"
        sentinel_bytes = b"foreign packet directory sentinel"
        original_write = blind_tool_module._write_exclusive_at
        switched = False
        opened_original_directory = False

        def rename_after_packet_open(
            directory_fd: int, name: str, raw: bytes
        ) -> tuple[int, int]:
            nonlocal switched, opened_original_directory
            if not switched and name.startswith("bp-"):
                held = os.fstat(directory_fd)
                current = self.packet_dir.stat()
                opened_original_directory = (
                    held.st_dev,
                    held.st_ino,
                ) == (current.st_dev, current.st_ino)
                self.packet_dir.rename(retired_packets)
                self.packet_dir.mkdir(mode=0o700)
                sentinel.write_bytes(sentinel_bytes)
                switched = True
            return original_write(directory_fd, name, raw)

        with (
            patch(
                "eval.blind_review.tool._write_exclusive_at",
                side_effect=rename_after_packet_open,
            ),
            self.assertRaises(BlindReviewError),
        ):
            self._prepare()

        self.assertTrue(switched)
        self.assertTrue(opened_original_directory)
        self.assertEqual(sentinel.read_bytes(), sentinel_bytes)
        self.assertEqual(
            sorted(path.name for path in self.packet_dir.iterdir()), ["keep.txt"]
        )
        self.assertTrue(retired_packets.is_dir())
        self.assertEqual(list(retired_packets.iterdir()), [])
        self.assertFalse(self.map_path.exists())

    def test_preexisting_map_inserted_after_path_check_is_preserved(self) -> None:
        original = blind_tool_module._validate_prepare_paths
        sentinel = b"foreign map sentinel"

        def insert_map(*args: Any) -> None:
            original(*args)
            self.map_path.parent.mkdir(mode=0o700)
            self.map_path.write_bytes(sentinel)

        with (
            patch(
                "eval.blind_review.tool._validate_prepare_paths",
                side_effect=insert_map,
            ),
            self.assertRaises(BlindReviewError),
        ):
            self._prepare()
        self.assertEqual(self.map_path.read_bytes(), sentinel)
        self.assertFalse(self.packet_dir.exists())

    def test_preexisting_packet_tree_inserted_after_path_check_is_preserved(
        self,
    ) -> None:
        original = blind_tool_module._validate_prepare_paths
        sentinel = b"foreign packet sentinel"
        sentinel_path = self.packet_dir / "keep.txt"

        def insert_packets(*args: Any) -> None:
            original(*args)
            self.packet_dir.mkdir(mode=0o700)
            sentinel_path.write_bytes(sentinel)

        with (
            patch(
                "eval.blind_review.tool._validate_prepare_paths",
                side_effect=insert_packets,
            ),
            self.assertRaises(BlindReviewError),
        ):
            self._prepare()
        self.assertEqual(sentinel_path.read_bytes(), sentinel)
        self.assertFalse(self.map_path.exists())

    def test_map_link_collision_after_packet_write_preserves_other_file(self) -> None:
        sentinel = b"foreign map after packet preparation"
        original_link = os.link
        collided = False

        def insert_map_before_link(
            source: str, destination: str, **kwargs: Any
        ) -> None:
            nonlocal collided
            if destination == self.map_path.name and not collided:
                self.map_path.write_bytes(sentinel)
                collided = True
            original_link(source, destination, **kwargs)

        with (
            patch("eval.scorecard.os.link", side_effect=insert_map_before_link),
            self.assertRaises(BlindReviewError),
        ):
            self._prepare()
        self.assertTrue(collided)
        self.assertEqual(self.map_path.read_bytes(), sentinel)
        self.assertFalse(self.packet_dir.exists())
        self.assertEqual(list(self.map_path.parent.glob(".scorecard-*.tmp")), [])

    def test_denies_missing_screening_or_unsafe_output_paths(self) -> None:
        bad = copy.deepcopy(self.observation)
        del bad["screening"]
        self._write_observations([bad])
        with self.assertRaises(BlindReviewError):
            self._prepare()
        self.assertFalse(self.packet_dir.exists())

        self._write_observations([self.observation])
        with self.assertRaises(BlindReviewError):
            prepare_packets(
                corpus_path=self.cases_path,
                sources_path=self.sources_path,
                rubric_path=self.rubric_path,
                observations_path=self.observations_path,
                packet_dir=Path("relative-packets"),
                map_path=self.map_path,
            )
        with self.assertRaises(BlindReviewError):
            prepare_packets(
                corpus_path=self.cases_path,
                sources_path=self.sources_path,
                rubric_path=self.rubric_path,
                observations_path=self.observations_path,
                packet_dir=self.packet_dir,
                map_path=self.packet_dir / "identity-map.json",
            )
        self.assertFalse(self.packet_dir.exists())

    @unittest.skipUnless(OPENSSL_BIN, "OpenSSL is required for signed witness test")
    def test_legacy_v1_witness_cannot_unblind(self) -> None:
        self._prepare_reviews()
        key_hash = self._sign_receipt()
        with self.assertRaises(BlindReviewError):
            self._unblind(key_hash)
        self.assertFalse(self.unblinded_path.exists())

    @unittest.skipUnless(OPENSSL_BIN, "OpenSSL is required for signed witness test")
    def test_one_cell_witness_cannot_reveal_partial_candidate_case_matrix(self) -> None:
        self._prepare_reviews()
        key_hash = self._sign_receipt()
        with self.assertRaises(BlindReviewError):
            self._unblind(key_hash)
        self.assertFalse(self.unblinded_path.exists())

    @unittest.skipUnless(OPENSSL_BIN, "OpenSSL is required for signed witness test")
    def test_second_signed_quality_reviewer_needs_new_aggregation_contract(
        self,
    ) -> None:
        _, reviews = self._prepare_reviews()
        second = copy.deepcopy(reviews["reviews"][0])
        second["reviewer_id"] = "second-blind-reviewer"
        reviews["reviews"].append(second)
        save(self.reviews_path, reviews)
        receipt = json.loads(self.receipt_path.read_text(encoding="utf-8"))
        receipt["reviews_sha256"] = file_hash(self.reviews_path)
        save(self.receipt_path, receipt)
        key_hash = self._sign_receipt()
        with self.assertRaises(BlindReviewError):
            self._unblind(key_hash)
        self.assertFalse(self.unblinded_path.exists())

    @unittest.skipUnless(OPENSSL_BIN, "OpenSSL is required for signed witness test")
    def test_tampering_or_missing_review_denies_unblind(self) -> None:
        _, reviews = self._prepare_reviews()
        key_hash = self._sign_receipt()
        reviews["reviews"][0]["scores"]["factual_accuracy"] = 0
        save(self.reviews_path, reviews)
        with self.assertRaises(BlindReviewError):
            self._unblind(key_hash)
        self.assertFalse(self.unblinded_path.exists())

        reviews["reviews"] = []
        save(self.reviews_path, reviews)
        with self.assertRaises(BlindReviewError):
            self._unblind(key_hash)
        self.assertFalse(self.unblinded_path.exists())

    @unittest.skipUnless(OPENSSL_BIN, "OpenSSL is required for signed witness test")
    def test_signed_map_cannot_claim_a_different_screened_packet_answer(self) -> None:
        self._prepare_reviews()
        key_hash = self._sign_receipt()
        concealed = json.loads(self.map_path.read_text(encoding="utf-8"))
        concealed["assignments"][0]["screening"]["packet_answer_sha256"] = "0" * 64
        save(self.map_path, concealed)
        receipt = json.loads(self.receipt_path.read_text(encoding="utf-8"))
        receipt["candidate_map_sha256"] = file_hash(self.map_path)
        save(self.receipt_path, receipt)
        assert OPENSSL_BIN is not None
        subprocess.run(
            [
                OPENSSL_BIN,
                "dgst",
                "-sha256",
                "-sign",
                str(self.private_key_path),
                "-out",
                str(self.signature_path),
                str(self.receipt_path),
            ],
            check=True,
            capture_output=True,
        )
        with self.assertRaises(BlindReviewError):
            self._unblind(key_hash)
        self.assertFalse(self.unblinded_path.exists())

    @unittest.skipUnless(OPENSSL_BIN, "OpenSSL is required for signed witness test")
    def test_resigned_packet_with_changed_approved_question_is_rejected(self) -> None:
        key_hash = self._resign_changed_packet("question")
        with self.assertRaises(BlindReviewError):
            self._unblind(key_hash)
        self.assertFalse(self.unblinded_path.exists())

    @unittest.skipUnless(OPENSSL_BIN, "OpenSSL is required for signed witness test")
    def test_resigned_packet_with_changed_source_snapshot_is_rejected(self) -> None:
        key_hash = self._resign_changed_packet("source_text")
        with self.assertRaises(BlindReviewError):
            self._unblind(key_hash)
        self.assertFalse(self.unblinded_path.exists())

    @unittest.skipUnless(OPENSSL_BIN, "OpenSSL is required for signed witness test")
    def test_resigned_packet_with_candidate_name_in_answer_is_rejected(self) -> None:
        key_hash = self._resign_changed_packet("answer_identity")
        with self.assertRaises(BlindReviewError):
            self._unblind(key_hash)
        self.assertFalse(self.unblinded_path.exists())

    @unittest.skipUnless(OPENSSL_BIN, "OpenSSL is required for signed witness test")
    def test_receipt_replacement_during_signature_check_denies_unblind(self) -> None:
        self._prepare_reviews()
        receipt = json.loads(self.receipt_path.read_text(encoding="utf-8"))
        receipt["witnessed_at"] = "2026-10-26T10:30:00Z"
        save(self.receipt_path, receipt)
        key_hash = self._sign_receipt()
        signed_early_receipt = self.receipt_path.read_bytes()
        receipt["witnessed_at"] = "2026-10-26T12:00:00Z"
        save(self.receipt_path, receipt)
        real_run = subprocess.run

        def swap_before_verify(*args: Any, **kwargs: Any) -> Any:
            self.receipt_path.write_bytes(signed_early_receipt)
            return real_run(*args, **kwargs)

        with (
            patch(
                "eval.blind_review.tool.subprocess.run", side_effect=swap_before_verify
            ),
            self.assertRaises(BlindReviewError),
        ):
            self._unblind(key_hash)
        self.assertFalse(self.unblinded_path.exists())

    @unittest.skipUnless(OPENSSL_BIN, "OpenSSL is required for signed witness test")
    def test_wrong_key_unsigned_receipt_and_late_review_deny(self) -> None:
        _, reviews = self._prepare_reviews()
        key_hash = self._sign_receipt()
        with self.assertRaises(BlindReviewError):
            self._unblind("0" * 64)
        self.signature_path.write_bytes(b"not a signature")
        with self.assertRaises(BlindReviewError):
            self._unblind(key_hash)

        reviews["reviews"][0]["reviewed_at"] = "2026-10-26T13:00:00Z"
        save(self.reviews_path, reviews)
        receipt = json.loads(self.receipt_path.read_text(encoding="utf-8"))
        receipt["reviews_sha256"] = file_hash(self.reviews_path)
        save(self.receipt_path, receipt)
        assert OPENSSL_BIN is not None
        subprocess.run(
            [
                OPENSSL_BIN,
                "dgst",
                "-sha256",
                "-sign",
                str(self.private_key_path),
                "-out",
                str(self.signature_path),
                str(self.receipt_path),
            ],
            check=True,
            capture_output=True,
        )
        with self.assertRaises(BlindReviewError):
            self._unblind(key_hash)
        self.assertFalse(self.unblinded_path.exists())

    @unittest.skipUnless(OPENSSL_BIN, "OpenSSL is required for signed witness test")
    def test_signed_review_missing_required_case_dimension_denies_unblind(self) -> None:
        _, reviews = self._prepare_reviews()
        del reviews["reviews"][0]["scores"]["completeness"]
        save(self.reviews_path, reviews)
        receipt = json.loads(self.receipt_path.read_text(encoding="utf-8"))
        receipt["reviews_sha256"] = file_hash(self.reviews_path)
        save(self.receipt_path, receipt)
        key_hash = self._sign_receipt()
        with self.assertRaises(BlindReviewError):
            self._unblind(key_hash)
        self.assertFalse(self.unblinded_path.exists())

    @unittest.skipUnless(OPENSSL_BIN, "OpenSSL is required for signed witness test")
    def test_signed_review_extra_case_dimension_denies_unblind(self) -> None:
        _, reviews = self._prepare_reviews()
        reviews["reviews"][0]["scores"]["abstention"] = 4
        save(self.reviews_path, reviews)
        receipt = json.loads(self.receipt_path.read_text(encoding="utf-8"))
        receipt["reviews_sha256"] = file_hash(self.reviews_path)
        save(self.receipt_path, receipt)
        key_hash = self._sign_receipt()
        with self.assertRaises(BlindReviewError):
            self._unblind(key_hash)
        self.assertFalse(self.unblinded_path.exists())

    @unittest.skipUnless(OPENSSL_BIN, "OpenSSL is required for signed witness test")
    def test_unblind_denies_repinned_invalid_dimensions_even_if_resigned(self) -> None:
        manifest, reviews = self._prepare_reviews()
        self.case["rubric_dimensions"] = ["factual_accuracy"]
        save(self.cases_path, self.cases)
        manifest["corpus_digest"] = digest(self.cases)
        save(self.packet_dir / "packet-manifest.json", manifest)
        manifest_hash = file_hash(self.packet_dir / "packet-manifest.json")
        concealed = json.loads(self.map_path.read_text(encoding="utf-8"))
        concealed["corpus_digest"] = manifest["corpus_digest"]
        concealed["packet_manifest_sha256"] = manifest_hash
        save(self.map_path, concealed)
        reviews["packet_manifest_sha256"] = manifest_hash
        reviews["reviews"][0]["scores"] = {"factual_accuracy": 4}
        save(self.reviews_path, reviews)
        receipt = json.loads(self.receipt_path.read_text(encoding="utf-8"))
        receipt["packet_manifest_sha256"] = manifest_hash
        receipt["candidate_map_sha256"] = file_hash(self.map_path)
        receipt["reviews_sha256"] = file_hash(self.reviews_path)
        save(self.receipt_path, receipt)
        key_hash = self._sign_receipt()
        with self.assertRaises(BlindReviewError):
            self._unblind(key_hash)
        self.assertFalse(self.unblinded_path.exists())

    @unittest.skipUnless(OPENSSL_BIN, "OpenSSL is required for signed witness test")
    def test_changed_verifier_digest_fails_closed(self) -> None:
        with (
            patch.object(blind_tool_module, "TRUSTED_VERIFIER_SHA256", "0" * 64),
            self.assertRaisesRegex(BlindReviewError, "trusted verifier digest changed"),
        ):
            blind_tool_module._trusted_verifier_path()

    @unittest.skipUnless(OPENSSL_BIN, "OpenSSL is required for signed witness test")
    def test_caller_supplied_fake_verifier_cannot_unblind_invalid_signature(
        self,
    ) -> None:
        self._prepare_reviews()
        key_hash = self._sign_receipt()
        self.signature_path.write_bytes(b"invalid signature")
        fake_verifier = self.root / "always-success"
        fake_verifier.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        fake_verifier.chmod(0o700)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "eval.blind_review.tool",
                "unblind",
                "--corpus",
                str(self.cases_path),
                "--sources",
                str(self.sources_path),
                "--rubric",
                str(self.rubric_path),
                "--packet-dir",
                str(self.packet_dir),
                "--map",
                str(self.map_path),
                "--reviews",
                str(self.reviews_path),
                "--receipt",
                str(self.receipt_path),
                "--signature",
                str(self.signature_path),
                "--public-key",
                str(self.public_key_path),
                "--trusted-key-sha256",
                key_hash,
                "--expected-witness-id",
                "independent-freeze-witness",
                "--output",
                str(self.unblinded_path),
                "--openssl-bin",
                str(fake_verifier),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.unblinded_path.exists())

    def test_cli_errors_do_not_echo_answer_or_source(self) -> None:
        self.observation["packet_answer"] = "SENSITIVE-ANSWER-CANARY chatgpt_enterprise"
        self.observation["screening"]["packet_answer_sha256"] = hashlib.sha256(
            self.observation["packet_answer"].encode()
        ).hexdigest()
        self._write_observations([self.observation])
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "eval.blind_review.tool",
                "prepare",
                "--corpus",
                str(self.cases_path),
                "--sources",
                str(self.sources_path),
                "--rubric",
                str(self.rubric_path),
                "--observations",
                str(self.observations_path),
                "--packet-dir",
                str(self.packet_dir),
                "--map",
                str(self.map_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("SENSITIVE-ANSWER-CANARY", result.stdout + result.stderr)
        self.assertNotIn("chatgpt_enterprise", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
