"""Synthetic signed-binding regressions; no candidate pilot was observed."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from jsonschema import Draft202012Validator, FormatChecker

from eval import binding as binding_module
from eval import scorecard as scorecard_module
from eval.blind_review import tool as blind_tool_module
from eval.blind_review.tool import BlindReviewError, prepare_packets, verify_and_unblind
from eval.scorecard import EvaluationError, build_scorecard, canonical_digest, main
from eval.tests.test_scorecard import fixture_inputs

ROOT = Path(__file__).resolve().parents[1]
OPENSSL = Path(shutil.which("openssl") or "/usr/bin/openssl")


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def artifact(ref: str) -> dict[str, str]:
    return {"ref": ref, "sha256": hashlib.sha256(ref.encode()).hexdigest()}


class SignedFixture:
    """Complete but test-only 3×20 packet set and local test signatures."""

    def __init__(
        self,
        root: Path,
        *,
        omit_last: bool = False,
        missing_citation: bool = False,
        metric_value: float | None = None,
        deferred_last: str | None = None,
    ) -> None:
        root = root.resolve(strict=True)
        self.root = root
        self.corpus, self.sources, self.rubric, self.runs = fixture_inputs()
        self.cases_by_id = {case["case_id"]: case for case in self.corpus["cases"]}
        self.sources_by_id = {
            source["evidence_id"]: source for source in self.sources["sources"]
        }
        self.corpus_path = root / "cases.json"
        self.sources_path = root / "sources.json"
        self.rubric_path = root / "rubric.json"
        self.observations_path = root / "raw-observations.json"
        self.packet_dir = root / "packets"
        self.map_path = root / "private" / "candidate-map.json"
        self.reviews_path = root / "reviews.json"
        self.control_path = root / "control-review.json"
        self.control_signature_path = root / "control-review.sig"
        self.control_private_path = root / "control-private.pem"
        self.control_public_path = root / "control-public.pem"
        self.receipt_path = root / "receipt.json"
        self.witness_signature_path = root / "receipt.sig"
        self.witness_private_path = root / "witness-private.pem"
        self.witness_public_path = root / "witness-public.pem"
        self.binding_path = root / "binding.json"
        self.unblinded_path = root / "private" / "unblinded.json"
        self.raw_observations: list[dict[str, Any]] = []
        for run in self.runs:
            for result in run["results"]:
                case_id = result["case_id"]
                run_id = result["run_id"]
                if metric_value is not None:
                    for field in ("latency_ms", "cost_usd", "user_effort_minutes"):
                        result[field] = metric_value
                if (
                    missing_citation
                    and run["candidate_id"] == "openshell_worker"
                    and case_id == "case-01"
                ):
                    result["citations"] = []
                answer = "A synthetic answer reviewed for this unit test."
                result["answer_artifact_ref"] = f"test:raw:{run_id}"
                result["review"]["reviewer_id"] = "blind-quality-reviewer"
                result["review"]["reviewed_at"] = "2026-10-26T14:00:00Z"
                result["review"]["notes"] = f"quality review for {run_id}"
                spans = []
                for citation in result["citations"]:
                    source_text = self.sources_by_id[citation["evidence_id"]]["text"]
                    start = source_text.index(citation["quote"])
                    spans.append(
                        {
                            **citation,
                            "start": start,
                            "end": start + len(citation["quote"]),
                        }
                    )
                self.raw_observations.append(
                    {
                        "status": "completed",
                        "case_id": case_id,
                        "candidate_id": run["candidate_id"],
                        "run_id": run_id,
                        "candidate_version": run["candidate_version"],
                        "model_version": "synthetic-model-v1",
                        "source_delivery": run["source_delivery"],
                        "answer_artifact_ref": result["answer_artifact_ref"],
                        "latency_ms": result["latency_ms"],
                        "cost_usd": result["cost_usd"],
                        "user_effort_minutes": result["user_effort_minutes"],
                        "raw_answer": answer,
                        "packet_answer": answer,
                        "screening": {
                            "custodian_id": "test-screening-custodian",
                            "screened_at": "2026-10-26T13:00:00Z",
                            "record_ref": f"test:screening:{run_id}",
                            "raw_answer_sha256": hashlib.sha256(
                                answer.encode()
                            ).hexdigest(),
                            "packet_answer_sha256": hashlib.sha256(
                                answer.encode()
                            ).hexdigest(),
                        },
                        "citations": spans,
                    }
                )
        if deferred_last is not None:
            assert deferred_last in ("deferred", "failed")
            omitted = self.raw_observations.pop()
            reason = (
                "Approved source path unavailable in this synthetic test"
                if deferred_last == "deferred"
                else "Synthetic worker attempt failed before answer capture"
            )
            self.runs[-1]["results"][-1] = {
                "case_id": omitted["case_id"],
                "status": deferred_last,
                "reason": reason,
            }
            self.raw_observations.append(
                {
                    "candidate_id": omitted["candidate_id"],
                    "case_id": omitted["case_id"],
                    "status": deferred_last,
                    "reason": reason,
                    "disposition_evidence": artifact(
                        f"test:disposition:{omitted['candidate_id']}:{omitted['case_id']}"
                    ),
                }
            )
        if omit_last:
            self.raw_observations.pop()
        save(self.corpus_path, self.corpus)
        save(self.sources_path, self.sources)
        save(self.rubric_path, self.rubric)
        save(
            self.observations_path,
            {
                "schema_version": 2,
                "cell_count": len(self.raw_observations),
                "corpus_digest": canonical_digest(self.corpus),
                "source_pack_digest": canonical_digest(self.sources),
                "rubric_digest": canonical_digest(self.rubric),
                "observations": self.raw_observations,
            },
        )
        self.manifest = prepare_packets(
            corpus_path=self.corpus_path,
            sources_path=self.sources_path,
            rubric_path=self.rubric_path,
            observations_path=self.observations_path,
            packet_dir=self.packet_dir,
            map_path=self.map_path,
        )
        self.map = json.loads(self.map_path.read_text(encoding="utf-8"))
        self.packet_by_id = {
            record["packet_id"]: json.loads(
                (self.packet_dir / f"{record['packet_id']}.json").read_text(
                    encoding="utf-8"
                )
            )
            for record in self.manifest["packets"]
        }
        self.results = {
            (run["candidate_id"], result["case_id"]): result
            for run in self.runs
            for result in run["results"]
        }
        self.write_reviews()
        self.control = self.make_control_review()
        save(self.control_path, self.control)
        self.make_key(self.control_private_path, self.control_public_path)
        self.make_key(self.witness_private_path, self.witness_public_path)
        self.sign(
            self.control_path, self.control_private_path, self.control_signature_path
        )
        self.write_receipt()
        self.write_binding()

    @staticmethod
    def make_key(private_path: Path, public_path: Path) -> None:
        subprocess.run(
            [
                str(OPENSSL),
                "genpkey",
                "-quiet",
                "-algorithm",
                "RSA",
                "-pkeyopt",
                "rsa_keygen_bits:2048",
                "-out",
                str(private_path),
            ],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                str(OPENSSL),
                "pkey",
                "-in",
                str(private_path),
                "-pubout",
                "-out",
                str(public_path),
            ],
            check=True,
            capture_output=True,
        )

    @staticmethod
    def sign(source: Path, private_path: Path, signature_path: Path) -> None:
        subprocess.run(
            [
                str(OPENSSL),
                "dgst",
                "-sha256",
                "-sign",
                str(private_path),
                "-out",
                str(signature_path),
                str(source),
            ],
            check=True,
            capture_output=True,
        )

    def write_reviews(self) -> None:
        reviews = []
        for assignment in self.map["assignments"]:
            result = self.results[(assignment["candidate_id"], assignment["case_id"])]
            review = result["review"]
            reviews.append(
                {
                    "packet_id": assignment["packet_id"],
                    "packet_sha256": assignment["packet_sha256"],
                    "reviewer_id": review["reviewer_id"],
                    "reviewed_at": review["reviewed_at"],
                    "scores": copy.deepcopy(review["scores"]),
                    "notes": review["notes"],
                }
            )
        save(
            self.reviews_path,
            {
                "schema_version": 1,
                "packet_manifest_sha256": file_hash(
                    self.packet_dir / "packet-manifest.json"
                ),
                "reviews": reviews,
            },
        )

    def make_control_review(self) -> dict[str, Any]:
        cases = []
        observation_by_run = {
            item["run_id"]: item
            for item in self.raw_observations
            if item["status"] == "completed"
        }
        for assignment in self.map["assignments"]:
            result = self.results[(assignment["candidate_id"], assignment["case_id"])]
            case = self.cases_by_id[assignment["case_id"]]
            raw = observation_by_run[assignment["run_id"]]
            events = []
            for kind, observation in (
                ("forbidden_probe", result.get("permission_probe")),
                ("allowed_probe", result.get("allowed_probe")),
                (
                    "revocation_pre_probe",
                    result.get("revocation_transition", {}).get("pre_probe"),
                ),
                (
                    "revocation_acknowledgement",
                    result.get("revocation_transition", {}).get("acknowledgement"),
                ),
                (
                    "revocation_post_probe",
                    result.get("revocation_transition", {}).get("post_probe"),
                ),
            ):
                if observation is not None:
                    events.append(
                        {
                            "kind": kind,
                            "observation": copy.deepcopy(observation),
                            "event_sha256": hashlib.sha256(
                                f"retained {kind} event for {assignment['run_id']}".encode()
                            ).hexdigest(),
                        }
                    )
            prompt_payload = None
            if case["category"] == "prompt_injection":
                sentinel = case["prompt_injection_sentinel"]
                source_id = next(
                    span["evidence_id"]
                    for span in case["expected_citation_spans"]
                    if sentinel in self.sources_by_id[span["evidence_id"]]["text"]
                )
                prompt_payload = {
                    "source_evidence_id": source_id,
                    "delivery": artifact(
                        f"test:payload-delivery:{assignment['run_id']}"
                    ),
                    "answer_inspection": artifact(
                        f"test:answer-inspection:{assignment['run_id']}"
                    ),
                }
            cases.append(
                {
                    "status": "completed",
                    "candidate_id": assignment["candidate_id"],
                    "case_id": assignment["case_id"],
                    "run_id": assignment["run_id"],
                    "observed_behavior": result["observed_behavior"],
                    "raw_answer_sha256": raw["screening"]["raw_answer_sha256"],
                    "raw_run_artifact": artifact(result["answer_artifact_ref"]),
                    "screening_record": artifact(raw["screening"]["record_ref"]),
                    "source_view": artifact(f"test:source-view:{assignment['run_id']}"),
                    "permission_violation": result["review"]["permission_violation"],
                    "prompt_injection_violation": result["review"][
                        "prompt_injection_violation"
                    ],
                    "permission_events": events,
                    "prompt_payload": prompt_payload,
                }
            )
        for disposition in self.map["dispositions"]:
            cases.append(
                {
                    **disposition,
                    "control_evidence": artifact(
                        "test:independent-disposition:"
                        f"{disposition['candidate_id']}:{disposition['case_id']}"
                    ),
                }
            )
        return {
            "schema_version": 2,
            "approval": {
                "status": "approved",
                "reviewer_id": "test-independent-control-reviewer",
                "reviewed_at": "2026-10-26T15:00:00Z",
                "basis": "independently_retained_raw_run_control_and_disposition_evidence",
            },
            "packet_manifest_sha256": file_hash(
                self.packet_dir / "packet-manifest.json"
            ),
            "candidate_map_sha256": file_hash(self.map_path),
            "blind_reviews_sha256": file_hash(self.reviews_path),
            "raw_observations_sha256": file_hash(self.observations_path),
            "candidate_run_digests": {
                run["candidate_id"]: canonical_digest(run) for run in self.runs
            },
            "cases": cases,
        }

    def write_receipt(self) -> None:
        save(
            self.receipt_path,
            {
                "schema_version": 3,
                "cell_count": self.manifest["cell_count"],
                "packet_count": self.manifest["packet_count"],
                "disposition_count": len(self.map["dispositions"]),
                "packet_manifest_sha256": file_hash(
                    self.packet_dir / "packet-manifest.json"
                ),
                "candidate_map_sha256": file_hash(self.map_path),
                "reviews_sha256": file_hash(self.reviews_path),
                "raw_observations_sha256": file_hash(self.observations_path),
                "control_review_sha256": file_hash(self.control_path),
                "control_signature_sha256": file_hash(self.control_signature_path),
                "witness_id": "test-independent-freeze-witness",
                "witness_public_key_sha256": file_hash(self.witness_public_path),
                "control_reviewer_id": "test-independent-control-reviewer",
                "control_public_key_sha256": file_hash(self.control_public_path),
                "witnessed_at": "2026-10-26T16:00:00Z",
            },
        )
        self.sign(
            self.receipt_path, self.witness_private_path, self.witness_signature_path
        )

    def resign(self) -> None:
        save(self.control_path, self.control)
        self.sign(
            self.control_path, self.control_private_path, self.control_signature_path
        )
        self.write_receipt()

    def resign_wrong_raw_answer_with_unchanged_scored_packet(self) -> None:
        observations = json.loads(self.observations_path.read_text(encoding="utf-8"))
        raw = observations["observations"][0]
        raw["raw_answer"] = "The fictional answer was wrong in the retained run."
        raw["screening"]["raw_answer_sha256"] = hashlib.sha256(
            raw["raw_answer"].encode("utf-8")
        ).hexdigest()
        save(self.observations_path, observations)
        self.raw_observations = observations["observations"]
        assignment = next(
            item for item in self.map["assignments"] if item["run_id"] == raw["run_id"]
        )
        assignment["screening"] = copy.deepcopy(raw["screening"])
        save(self.map_path, self.map)
        self.control = self.make_control_review()
        self.resign()

    def write_binding(self) -> None:
        save(
            self.binding_path,
            {
                "schema_version": 2,
                "approved_corpus_path": str(self.corpus_path),
                "approved_sources_path": str(self.sources_path),
                "approved_rubric_path": str(self.rubric_path),
                "raw_observations_path": str(self.observations_path),
                "packet_directory": str(self.packet_dir),
                "candidate_map_path": str(self.map_path),
                "blind_reviews_path": str(self.reviews_path),
                "witness_receipt_path": str(self.receipt_path),
                "witness_signature_path": str(self.witness_signature_path),
                "witness_public_key_path": str(self.witness_public_path),
                "control_review_path": str(self.control_path),
                "control_signature_path": str(self.control_signature_path),
                "control_public_key_path": str(self.control_public_path),
            },
        )

    def score(self) -> dict[str, Any]:
        return build_scorecard(
            self.corpus,
            self.sources,
            self.rubric,
            self.runs,
            binding_manifest_path=self.binding_path,
            witness_key_sha256=file_hash(self.witness_public_path),
            witness_id="test-independent-freeze-witness",
            control_key_sha256=file_hash(self.control_public_path),
            control_reviewer_id="test-independent-control-reviewer",
        )

    def unblind(self) -> dict[str, Any]:
        return verify_and_unblind(
            corpus_path=self.corpus_path,
            sources_path=self.sources_path,
            rubric_path=self.rubric_path,
            raw_observations_path=self.observations_path,
            packet_dir=self.packet_dir,
            map_path=self.map_path,
            reviews_path=self.reviews_path,
            receipt_path=self.receipt_path,
            signature_path=self.witness_signature_path,
            public_key_path=self.witness_public_path,
            trusted_key_sha256=file_hash(self.witness_public_path),
            expected_witness_id="test-independent-freeze-witness",
            control_review_path=self.control_path,
            control_signature_path=self.control_signature_path,
            control_public_key_path=self.control_public_path,
            trusted_control_key_sha256=file_hash(self.control_public_path),
            expected_control_reviewer_id="test-independent-control-reviewer",
            output_path=self.unblinded_path,
        )

    def cli_args(self) -> list[str]:
        run_paths = []
        for run in self.runs:
            path = self.root / f"candidate-{run['candidate_id']}.json"
            save(path, run)
            run_paths.append(str(path))
        return [
            "--corpus",
            str(self.corpus_path),
            "--sources",
            str(self.sources_path),
            "--rubric",
            str(self.rubric_path),
            "--runs",
            *run_paths,
            "--binding-manifest",
            str(self.binding_path),
            "--witness-key-sha256",
            file_hash(self.witness_public_path),
            "--witness-id",
            "test-independent-freeze-witness",
            "--control-key-sha256",
            file_hash(self.control_public_path),
            "--control-reviewer-id",
            "test-independent-control-reviewer",
        ]


@unittest.skipUnless(OPENSSL.is_file(), "qualified verifier is unavailable")
class SignedBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.fixture = SignedFixture(Path(self.temporary.name))

    def _unblind_route_fixture(self) -> tuple[Path, Path, Path]:
        f = self.fixture
        reviewer_root = f.root / "reviewer-output"
        reviewer_root.mkdir()
        packet_dir = reviewer_root / "private"
        f.packet_dir.rename(packet_dir)
        f.packet_dir = packet_dir
        attacker = f.root / "attacker-output"
        attacker.mkdir()
        route = attacker / "route"
        route.symlink_to(f.root, target_is_directory=True)
        f.unblinded_path = route / "private" / "unblinded.json"
        return route, reviewer_root, packet_dir

    def test_unbound_labeled_runs_cannot_claim_ready(self) -> None:
        f = self.fixture
        report = build_scorecard(f.corpus, f.sources, f.rubric, f.runs)
        self.assertEqual(report["decision_readiness"], "incomplete")
        self.assertEqual(report["binding"]["status"], "missing")

    def test_valid_full_synthetic_binding_allows_only_human_decision_readiness(
        self,
    ) -> None:
        f = self.fixture
        report = f.score()
        self.assertEqual(report["decision_readiness"], "ready_for_human_decision")
        self.assertEqual(report["binding"]["status"], "verified_local")
        self.assertEqual(report["binding"]["packet_count"], 60)
        self.assertEqual(report["schema_version"], 4)
        self.assertEqual(f.unblind()["packet_count"], 60)
        self.assertEqual(f.unblinded_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(list(f.unblinded_path.parent.glob(".scorecard-*.tmp")), [])

    def test_absent_or_invalid_witness_or_control_signature_denies(self) -> None:
        f = self.fixture
        f.witness_signature_path.unlink()
        with self.assertRaises((EvaluationError, BlindReviewError)):
            f.score()
        f.write_receipt()
        f.witness_signature_path.write_bytes(b"not a signature")
        with self.assertRaises((EvaluationError, BlindReviewError)):
            f.score()
        f.write_receipt()
        f.control_signature_path.write_bytes(b"not a signature")
        f.write_receipt()
        with self.assertRaises((EvaluationError, BlindReviewError)):
            f.score()

    def test_changed_or_copied_labeled_quality_review_denies(self) -> None:
        f = self.fixture
        first = f.runs[0]["results"][0]["review"]
        second = f.runs[0]["results"][1]["review"]
        f.runs[0]["results"][1]["review"] = copy.deepcopy(first)
        f.control["candidate_run_digests"][f.runs[0]["candidate_id"]] = (
            canonical_digest(f.runs[0])
        )
        f.resign()
        with self.assertRaises((EvaluationError, BlindReviewError)):
            f.score()
        f.runs[0]["results"][1]["review"] = second
        signed_reviews = json.loads(f.reviews_path.read_text(encoding="utf-8"))
        signed_reviews["reviews"][0]["scores"][
            next(iter(signed_reviews["reviews"][0]["scores"]))
        ] = 0
        save(f.reviews_path, signed_reviews)
        with self.assertRaises((EvaluationError, BlindReviewError)):
            f.score()

    def test_wrong_candidate_case_or_run_denies_even_if_control_is_resigned(
        self,
    ) -> None:
        f = self.fixture
        result = f.runs[0]["results"][0]
        original_run = result["run_id"]
        result["run_id"] = "synthetic-substituted-run"
        f.control["candidate_run_digests"][f.runs[0]["candidate_id"]] = (
            canonical_digest(f.runs[0])
        )
        matching_control = next(
            item for item in f.control["cases"] if item["run_id"] == original_run
        )
        matching_control["run_id"] = result["run_id"]
        f.resign()
        with self.assertRaises((EvaluationError, BlindReviewError)):
            f.score()
        result["run_id"] = original_run
        matching_control["run_id"] = original_run
        result["case_id"] = "synthetic-wrong-case"
        f.control["candidate_run_digests"][f.runs[0]["candidate_id"]] = (
            canonical_digest(f.runs[0])
        )
        f.resign()
        with self.assertRaises((EvaluationError, BlindReviewError)):
            f.score()

    def test_post_reveal_candidate_metadata_swap_denies(self) -> None:
        f = self.fixture
        f.runs[0]["tenant_entitlement"] = "swapped-after-freeze"
        with self.assertRaises((EvaluationError, BlindReviewError)):
            f.score()
        f.runs[0]["tenant_entitlement"] = "unit-test-only-no-real-tenant"
        f.runs[0]["candidate_version"] = "swapped-version"
        f.control["candidate_run_digests"][f.runs[0]["candidate_id"]] = (
            canonical_digest(f.runs[0])
        )
        f.resign()
        with self.assertRaises((EvaluationError, BlindReviewError)):
            f.score()

    def test_caller_mutation_between_scoring_and_binding_cannot_launder_quality(
        self,
    ) -> None:
        f = self.fixture
        target = next(
            result
            for result in f.runs[2]["results"]
            if f.cases_by_id[result["case_id"]]["category"] == "prompt_injection"
        )
        dimension = "prompt_injection_resistance"
        target["review"]["scores"][dimension] = 0
        f.write_reviews()
        f.control = f.make_control_review()
        f.resign()
        target["review"]["scores"][dimension] = 4
        original_score_result = scorecard_module._score_result

        def mutate_caller_after_score(*args: Any, **kwargs: Any) -> dict[str, Any]:
            scored = original_score_result(*args, **kwargs)
            if args[0]["run_id"] == target["run_id"]:
                target["review"]["scores"][dimension] = 0
            return scored

        with (
            patch(
                "eval.scorecard._score_result",
                side_effect=mutate_caller_after_score,
            ),
            self.assertRaises(EvaluationError),
        ):
            f.score()

    def test_approved_input_path_swap_between_reads_denies(self) -> None:
        f = self.fixture
        frozen_corpus = copy.deepcopy(f.corpus)
        caller_corpus = copy.deepcopy(f.corpus)
        caller_corpus["corpus_id"] = "synthetic-corpus-swapped-between-reads"
        f.corpus = caller_corpus
        for run in f.runs:
            run["corpus_digest"] = canonical_digest(caller_corpus)
        f.control["candidate_run_digests"] = {
            run["candidate_id"]: canonical_digest(run) for run in f.runs
        }
        f.resign()
        read_json = binding_module._read_json

        def swap_corpus(
            path: Path, limit: int, label: str
        ) -> tuple[dict[str, Any], bytes]:
            if path != f.corpus_path:
                return read_json(path, limit, label)
            save(path, caller_corpus)
            try:
                return read_json(path, limit, label)
            finally:
                save(path, frozen_corpus)

        with (
            patch("eval.binding._read_json", side_effect=swap_corpus),
            self.assertRaises(EvaluationError),
        ):
            f.score()

    def test_wrong_candidate_arm_cannot_reuse_another_signed_packet_set(self) -> None:
        f = self.fixture
        f.runs[0]["candidate_id"] = "different-candidate"
        with self.assertRaises((EvaluationError, BlindReviewError)):
            f.score()

    def test_score_or_dimension_drift_denies_even_if_control_is_resigned(self) -> None:
        f = self.fixture
        result = f.runs[0]["results"][0]
        dimension = next(iter(result["review"]["scores"]))
        result["review"]["scores"][dimension] = 3
        f.control["candidate_run_digests"][f.runs[0]["candidate_id"]] = (
            canonical_digest(f.runs[0])
        )
        f.resign()
        with self.assertRaises((EvaluationError, BlindReviewError)):
            f.score()
        result["review"]["scores"][dimension] = 4
        result["review"]["scores"]["abstention"] = 4
        f.control["candidate_run_digests"][f.runs[0]["candidate_id"]] = (
            canonical_digest(f.runs[0])
        )
        f.resign()
        with self.assertRaises((EvaluationError, BlindReviewError)):
            f.score()

    def test_partial_pre_reveal_matrix_cannot_unblind_or_score(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            f = SignedFixture(Path(temporary), omit_last=True)
            with self.assertRaises((EvaluationError, BlindReviewError)):
                f.unblind()
            with self.assertRaises((EvaluationError, BlindReviewError)):
                f.score()

    def test_complete_signed_deferred_cell_is_verified_but_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            f = SignedFixture(Path(temporary), deferred_last="deferred")
            omitted = f.runs[-1]["results"][-1]
            report = f.score()
            self.assertEqual(report["binding"]["status"], "verified_local")
            self.assertEqual(report["decision_readiness"], "incomplete")
            self.assertEqual(
                report["candidates"]["openshell_worker"]["deferred_cases"],
                [omitted["case_id"]],
            )

    def test_signed_completed_violation_blocks_even_with_deferred_cell(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            f = SignedFixture(Path(temporary), deferred_last="failed")
            denial = next(
                result
                for result in f.runs[2]["results"]
                if f.cases_by_id[result["case_id"]]["category"] == "permission_denial"
            )
            denial["permission_probe"]["outcome"] = "allowed"
            f.control = f.make_control_review()
            f.resign()
            report = f.score()
            self.assertEqual(report["binding"]["status"], "verified_local")
            self.assertEqual(
                report["decision_readiness"], "blocked_by_observed_violation"
            )

    def test_signed_quality_sentinel_blocks_even_with_deferred_cell(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            f = SignedFixture(
                Path(temporary), deferred_last="deferred", missing_citation=True
            )
            report = f.score()
            self.assertEqual(report["binding"]["status"], "verified_local")
            self.assertEqual(
                report["decision_readiness"], "blocked_by_quality_threshold"
            )
            self.assertIn(
                "case-01",
                report["candidates"]["openshell_worker"]["quality_sentinel_case_ids"],
            )

    def test_signed_failed_cell_without_observed_run_is_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            f = SignedFixture(Path(temporary), deferred_last="failed")
            report = f.score()
            self.assertEqual(report["decision_readiness"], "incomplete")
            self.assertEqual(report["binding"]["cell_count"], 60)
            self.assertEqual(report["binding"]["packet_count"], 59)
            self.assertEqual(report["binding"]["disposition_count"], 1)
            self.assertEqual(
                report["candidates"]["openshell_worker"]["failed_cases"],
                [f.runs[-1]["results"][-1]["case_id"]],
            )

    def test_signed_disposition_missing_duplicate_or_misclassified_denies(self) -> None:
        for mutation in ("missing", "duplicate", "misclassified"):
            with (
                self.subTest(mutation=mutation),
                tempfile.TemporaryDirectory() as temporary,
            ):
                f = SignedFixture(Path(temporary), deferred_last="deferred")
                if mutation == "missing":
                    raw = json.loads(f.observations_path.read_text())
                    raw["observations"].pop()
                    save(f.observations_path, raw)
                    f.control["raw_observations_sha256"] = file_hash(
                        f.observations_path
                    )
                else:
                    if mutation == "duplicate":
                        f.map["dispositions"].append(
                            copy.deepcopy(f.map["dispositions"][0])
                        )
                    else:
                        f.map["dispositions"][0]["status"] = "completed"
                    save(f.map_path, f.map)
                    f.control["candidate_map_sha256"] = file_hash(f.map_path)
                f.resign()
                with self.assertRaises((EvaluationError, BlindReviewError)):
                    f.unblind()
                with self.assertRaises((EvaluationError, BlindReviewError)):
                    f.score()

    def test_signed_disposition_change_or_fabricated_score_denies(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            f = SignedFixture(Path(temporary), deferred_last="deferred")
            result = f.runs[-1]["results"][-1]
            result["reason"] = "Changed after the witness freeze"
            f.control["candidate_run_digests"][f.runs[-1]["candidate_id"]] = (
                canonical_digest(f.runs[-1])
            )
            f.resign()
            with self.assertRaises(EvaluationError):
                f.score()
            result["reason"] = f.map["dispositions"][0]["reason"]
            result["review"] = {"scores": {"factual_accuracy": 4}}
            with self.assertRaises(EvaluationError):
                f.score()

    def test_signed_noncompleted_control_needs_independent_evidence(self) -> None:
        for mutation in ("missing", "self_attested"):
            with (
                self.subTest(mutation=mutation),
                tempfile.TemporaryDirectory() as temporary,
            ):
                f = SignedFixture(Path(temporary), deferred_last="deferred")
                disposition = next(
                    item for item in f.control["cases"] if item["status"] == "deferred"
                )
                if mutation == "missing":
                    del disposition["control_evidence"]
                else:
                    disposition["control_evidence"] = copy.deepcopy(
                        disposition["disposition_evidence"]
                    )
                f.resign()
                with self.assertRaises((EvaluationError, BlindReviewError)):
                    f.score()

    def test_old_signed_partial_contract_versions_are_rejected(self) -> None:
        for artifact_name, old_version in (
            ("binding", 1),
            ("control", 1),
            ("receipt", 2),
        ):
            with (
                self.subTest(artifact=artifact_name),
                tempfile.TemporaryDirectory() as temporary,
            ):
                f = SignedFixture(Path(temporary), deferred_last="deferred")
                if artifact_name == "binding":
                    binding = json.loads(f.binding_path.read_text())
                    binding["schema_version"] = old_version
                    save(f.binding_path, binding)
                elif artifact_name == "control":
                    f.control["schema_version"] = old_version
                    f.resign()
                else:
                    receipt = json.loads(f.receipt_path.read_text())
                    receipt["schema_version"] = old_version
                    save(f.receipt_path, receipt)
                    f.sign(
                        f.receipt_path,
                        f.witness_private_path,
                        f.witness_signature_path,
                    )
                with self.assertRaises((EvaluationError, BlindReviewError)):
                    f.score()

    def test_multiple_signed_quality_reviewers_cannot_be_aggregated_silently(
        self,
    ) -> None:
        f = self.fixture
        reviews = json.loads(f.reviews_path.read_text(encoding="utf-8"))
        extra = copy.deepcopy(reviews["reviews"][0])
        extra["reviewer_id"] = "second-quality-reviewer"
        reviews["reviews"].append(extra)
        save(f.reviews_path, reviews)
        f.control["blind_reviews_sha256"] = file_hash(f.reviews_path)
        f.resign()
        with self.assertRaises((EvaluationError, BlindReviewError)):
            f.score()
        with self.assertRaises((EvaluationError, BlindReviewError)):
            f.unblind()

    def test_missing_or_self_attested_permission_control_evidence_denies(self) -> None:
        f = self.fixture
        permission = next(
            item
            for item in f.control["cases"]
            if f.cases_by_id[item["case_id"]]["category"] == "permission_allowed"
        )
        permission["permission_events"] = []
        f.resign()
        with self.assertRaises((EvaluationError, BlindReviewError)):
            f.score()
        f.control = f.make_control_review()
        f.control["approval"] = {"status": "pending"}
        f.resign()
        with self.assertRaises((EvaluationError, BlindReviewError)):
            f.score()

    def test_missing_prompt_payload_delivery_or_answer_inspection_denies(self) -> None:
        f = self.fixture
        prompt = next(
            item
            for item in f.control["cases"]
            if f.cases_by_id[item["case_id"]]["category"] == "prompt_injection"
        )
        prompt["prompt_payload"] = None
        f.resign()
        with self.assertRaises((EvaluationError, BlindReviewError)):
            f.score()
        f.control = f.make_control_review()
        prompt = next(
            item
            for item in f.control["cases"]
            if f.cases_by_id[item["case_id"]]["category"] == "prompt_injection"
        )
        del prompt["prompt_payload"]["answer_inspection"]
        f.resign()
        with self.assertRaises((EvaluationError, BlindReviewError)):
            f.score()

    def test_raw_observation_bytes_and_answer_hash_are_bound(self) -> None:
        f = self.fixture
        raw = json.loads(f.observations_path.read_text(encoding="utf-8"))
        raw["observations"][0]["raw_answer"] += " altered after review"
        save(f.observations_path, raw)
        with self.assertRaises((EvaluationError, BlindReviewError)):
            f.score()

    def test_resigned_raw_packet_answer_drift_cannot_release_labels(self) -> None:
        f = self.fixture
        raw = json.loads(f.observations_path.read_text(encoding="utf-8"))
        changed = raw["observations"][0]
        changed["packet_answer"] += " changed after screening"
        changed["screening"]["packet_answer_sha256"] = hashlib.sha256(
            changed["packet_answer"].encode()
        ).hexdigest()
        save(f.observations_path, raw)
        f.control["raw_observations_sha256"] = file_hash(f.observations_path)
        f.resign()
        with self.assertRaises((EvaluationError, BlindReviewError)):
            f.unblind()
        self.assertFalse(f.unblinded_path.exists())

    def test_fully_resigned_wrong_raw_answer_cannot_unblind_scored_packet(self) -> None:
        f = self.fixture
        f.resign_wrong_raw_answer_with_unchanged_scored_packet()
        with self.assertRaises(BlindReviewError):
            f.unblind()
        self.assertFalse(f.unblinded_path.exists())

    def test_fully_resigned_wrong_raw_answer_cannot_claim_scorecard_ready(self) -> None:
        f = self.fixture
        f.resign_wrong_raw_answer_with_unchanged_scored_packet()
        with self.assertRaises(EvaluationError):
            f.score()

    def test_unblind_output_ancestor_a_b_a_switch_cannot_release_labels(self) -> None:
        f = self.fixture
        route, reviewer_root, packet_dir = self._unblind_route_fixture()
        original_open = os.open
        switched = False

        def switch_before_private_open(
            path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
            flags: int,
            *args: Any,
            **kwargs: Any,
        ) -> int:
            nonlocal switched
            if not switched and (
                path == f.unblinded_path
                or (path == "private" and kwargs.get("dir_fd") is not None)
            ):
                route.unlink()
                route.symlink_to(reviewer_root, target_is_directory=True)
                switched = True
                try:
                    return original_open(path, flags, *args, **kwargs)
                finally:
                    route.unlink()
                    route.symlink_to(f.root, target_is_directory=True)
            return original_open(path, flags, *args, **kwargs)

        rejected = False
        with patch(
            "eval.blind_review.tool.os.open", side_effect=switch_before_private_open
        ):
            try:
                f.unblind()
            except BlindReviewError:
                rejected = True
        self.assertFalse(switched)
        self.assertFalse((packet_dir / "unblinded.json").exists())
        self.assertFalse((f.map_path.parent / "unblinded.json").exists())
        self.assertEqual(list(packet_dir.glob(".scorecard-*.tmp")), [])
        self.assertEqual(list(f.map_path.parent.glob(".scorecard-*.tmp")), [])
        self.assertTrue(rejected)

    def test_unblind_output_ancestor_switch_that_stays_in_packets_denies(self) -> None:
        f = self.fixture
        route, reviewer_root, packet_dir = self._unblind_route_fixture()
        original_open = os.open
        switched = False

        def switch_before_private_open(
            path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
            flags: int,
            *args: Any,
            **kwargs: Any,
        ) -> int:
            nonlocal switched
            if not switched and (
                path == f.unblinded_path
                or (path == "private" and kwargs.get("dir_fd") is not None)
            ):
                route.unlink()
                route.symlink_to(reviewer_root, target_is_directory=True)
                switched = True
            return original_open(path, flags, *args, **kwargs)

        rejected = False
        try:
            with patch(
                "eval.blind_review.tool.os.open", side_effect=switch_before_private_open
            ):
                try:
                    f.unblind()
                except BlindReviewError:
                    rejected = True
        finally:
            if route.is_symlink():
                route.unlink()
                route.symlink_to(f.root, target_is_directory=True)
        self.assertFalse(switched)
        self.assertFalse((packet_dir / "unblinded.json").exists())
        self.assertFalse((f.map_path.parent / "unblinded.json").exists())
        self.assertEqual(list(packet_dir.glob(".scorecard-*.tmp")), [])
        self.assertEqual(list(f.map_path.parent.glob(".scorecard-*.tmp")), [])
        self.assertTrue(rejected)

    def test_unblind_output_route_switch_after_link_rolls_back_owned_file(
        self,
    ) -> None:
        f = self.fixture
        private_parent = f.unblinded_path.parent
        parked_parent = f.root / "private-parked"
        original_link = os.link
        switched = False

        def switch_after_link(source: str, destination: str, **kwargs: Any) -> None:
            nonlocal switched
            original_link(source, destination, **kwargs)
            if destination == f.unblinded_path.name and not switched:
                private_parent.rename(parked_parent)
                private_parent.mkdir(mode=0o700)
                switched = True

        try:
            with (
                patch("eval.scorecard.os.link", side_effect=switch_after_link),
                self.assertRaises(BlindReviewError),
            ):
                f.unblind()
        finally:
            if switched:
                private_parent.rmdir()
                parked_parent.rename(private_parent)
        self.assertTrue(switched)
        self.assertFalse(f.unblinded_path.exists())
        self.assertEqual(list(private_parent.glob(".scorecard-*.tmp")), [])

    def test_v1_receipt_and_wrong_trust_pin_cannot_support_readiness(self) -> None:
        f = self.fixture
        receipt = json.loads(f.receipt_path.read_text(encoding="utf-8"))
        receipt["schema_version"] = 1
        for field in (
            "control_review_sha256",
            "control_signature_sha256",
            "witness_public_key_sha256",
            "control_reviewer_id",
            "control_public_key_sha256",
        ):
            del receipt[field]
        save(f.receipt_path, receipt)
        f.sign(f.receipt_path, f.witness_private_path, f.witness_signature_path)
        with self.assertRaises((EvaluationError, BlindReviewError)):
            f.score()
        f.write_receipt()
        with self.assertRaises((EvaluationError, BlindReviewError)):
            build_scorecard(
                f.corpus,
                f.sources,
                f.rubric,
                f.runs,
                binding_manifest_path=f.binding_path,
                witness_key_sha256="0" * 64,
                witness_id="test-independent-freeze-witness",
                control_key_sha256=file_hash(f.control_public_path),
                control_reviewer_id="test-independent-control-reviewer",
            )

    def test_signed_lower_quality_remains_blocked_after_binding(self) -> None:
        f = self.fixture
        for result in f.runs[2]["results"]:
            result["review"]["scores"] = {
                dimension: 3 for dimension in result["review"]["scores"]
            }
        f.write_reviews()
        f.control = f.make_control_review()
        f.resign()
        report = f.score()
        self.assertEqual(report["binding"]["status"], "verified_local")
        self.assertEqual(report["decision_readiness"], "blocked_by_quality_threshold")
        self.assertLess(report["candidates"]["openshell_worker"]["mean_quality"], 80)

    def test_signed_finite_case_metrics_cannot_overflow_aggregate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            f = SignedFixture(Path(temporary), metric_value=1e308)
            with self.assertRaises(EvaluationError):
                f.score()

    def test_huge_integer_metric_rejects_as_evaluation_error(self) -> None:
        f = self.fixture
        f.runs[0]["results"][0]["latency_ms"] = 10**400
        with self.assertRaises(EvaluationError):
            f.score()

    def test_verified_permission_probe_violation_hard_blocks(self) -> None:
        f = self.fixture
        result = next(
            result
            for result in f.runs[2]["results"]
            if f.cases_by_id[result["case_id"]]["category"] == "permission_denial"
        )
        result["permission_probe"]["outcome"] = "allowed"
        f.control = f.make_control_review()
        f.resign()
        report = f.score()
        self.assertEqual(report["binding"]["status"], "verified_local")
        self.assertEqual(report["decision_readiness"], "blocked_by_observed_violation")
        self.assertEqual(
            report["candidates"]["openshell_worker"]["permission_violations"], 1
        )

    def test_verified_missing_citation_quality_sentinel_hard_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            f = SignedFixture(Path(temporary), missing_citation=True)
            report = f.score()
            self.assertEqual(report["binding"]["status"], "verified_local")
            self.assertEqual(
                report["decision_readiness"], "blocked_by_quality_threshold"
            )
            self.assertEqual(
                report["candidates"]["openshell_worker"]["quality_sentinel_case_ids"],
                ["case-01"],
            )

    def test_binding_control_and_receipt_schemas_accept_fixture(self) -> None:
        f = self.fixture
        for name, instance in (
            (
                "raw-observations.schema.json",
                json.loads(f.observations_path.read_text()),
            ),
            (
                "packet-manifest.schema.json",
                json.loads((f.packet_dir / "packet-manifest.json").read_text()),
            ),
            ("concealed-map.schema.json", f.map),
            ("scorer-binding.schema.json", json.loads(f.binding_path.read_text())),
            ("control-review.schema.json", f.control),
            ("witness-receipt.schema.json", json.loads(f.receipt_path.read_text())),
        ):
            schema = json.loads((ROOT / "schemas" / name).read_text())
            Draft202012Validator.check_schema(schema)
            Draft202012Validator(schema, format_checker=FormatChecker()).validate(
                instance
            )

    def test_partial_disposition_and_scorecard_v4_schemas_accept_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            f = SignedFixture(Path(temporary), deferred_last="deferred")
            artifacts = (
                ("raw-observations.schema.json", f.observations_path),
                ("packet-manifest.schema.json", f.packet_dir / "packet-manifest.json"),
                ("concealed-map.schema.json", f.map_path),
                ("control-review.schema.json", f.control_path),
                ("witness-receipt.schema.json", f.receipt_path),
                ("scorer-binding.schema.json", f.binding_path),
            )
            for name, path in artifacts:
                with self.subTest(name=name):
                    schema = json.loads((ROOT / "schemas" / name).read_text())
                    Draft202012Validator.check_schema(schema)
                    Draft202012Validator(
                        schema, format_checker=FormatChecker()
                    ).validate(json.loads(path.read_text()))
            schema = json.loads((ROOT / "schemas/scorecard.schema.json").read_text())
            Draft202012Validator(schema, format_checker=FormatChecker()).validate(
                f.score()
            )

            raw_schema = json.loads(
                (ROOT / "schemas/raw-observations.schema.json").read_text()
            )
            raw = json.loads(f.observations_path.read_text())
            raw["observations"][-1]["raw_answer"] = "fabricated answer"
            self.assertFalse(Draft202012Validator(raw_schema).is_valid(raw))
            control_schema = json.loads(
                (ROOT / "schemas/control-review.schema.json").read_text()
            )
            control = copy.deepcopy(f.control)
            control["cases"][-1].pop("control_evidence")
            self.assertFalse(Draft202012Validator(control_schema).is_valid(control))

    def test_scorecard_v4_schema_rejects_unbound_ready_claim(self) -> None:
        f = self.fixture
        report = build_scorecard(f.corpus, f.sources, f.rubric, f.runs)
        report["decision_readiness"] = "ready_for_human_decision"
        schema = json.loads((ROOT / "schemas/scorecard.schema.json").read_text())
        self.assertFalse(Draft202012Validator(schema).is_valid(report))

    def test_binding_contract_schemas_reject_unknown_or_old_versions(self) -> None:
        f = self.fixture
        binding_schema = json.loads(
            (ROOT / "schemas/scorer-binding.schema.json").read_text()
        )
        binding = json.loads(f.binding_path.read_text())
        binding["unblinded_result_path"] = "/untrusted/unblinded.json"
        self.assertFalse(Draft202012Validator(binding_schema).is_valid(binding))
        control_schema = json.loads(
            (ROOT / "schemas/control-review.schema.json").read_text()
        )
        control = copy.deepcopy(f.control)
        control["approval"] = {"status": "approved", "reviewer_id": "self"}
        self.assertFalse(Draft202012Validator(control_schema).is_valid(control))
        receipt_schema = json.loads(
            (ROOT / "schemas/witness-receipt.schema.json").read_text()
        )
        receipt = json.loads(f.receipt_path.read_text())
        receipt["schema_version"] = 1
        self.assertFalse(Draft202012Validator(receipt_schema).is_valid(receipt))
        versions = (
            ("raw-observations.schema.json", f.observations_path, 1),
            ("packet-manifest.schema.json", f.packet_dir / "packet-manifest.json", 1),
            ("concealed-map.schema.json", f.map_path, 1),
            ("scorer-binding.schema.json", f.binding_path, 1),
            ("control-review.schema.json", f.control_path, 1),
            ("witness-receipt.schema.json", f.receipt_path, 2),
        )
        for name, path, old_version in versions:
            with self.subTest(name=name):
                schema = json.loads((ROOT / "schemas" / name).read_text())
                old = json.loads(path.read_text())
                old["schema_version"] = old_version
                self.assertFalse(Draft202012Validator(schema).is_valid(old))
        scorecard_schema = json.loads(
            (ROOT / "schemas/scorecard.schema.json").read_text()
        )
        old_scorecard = f.score()
        old_scorecard["schema_version"] = 3
        self.assertFalse(Draft202012Validator(scorecard_schema).is_valid(old_scorecard))

    def test_cli_candidate_runs_require_private_output_even_when_unbound(self) -> None:
        f = self.fixture
        signed_args = f.cli_args()
        unbound_args = signed_args[: signed_args.index("--binding-manifest")]
        catalog_only_args = [
            "--corpus",
            str(f.corpus_path),
            "--sources",
            str(f.sources_path),
            "--rubric",
            str(f.rubric_path),
            "--binding-manifest",
            str(f.binding_path),
        ]
        for name, args in (
            ("unbound", [*unbound_args, "--allow-incomplete"]),
            ("signed", [*signed_args, "--allow-incomplete"]),
            ("catalog-only", catalog_only_args),
        ):
            with self.subTest(name=name):
                output, errors = io.StringIO(), io.StringIO()
                with redirect_stdout(output), redirect_stderr(errors):
                    self.assertEqual(main(args), 2)
                self.assertEqual(output.getvalue(), "")
                self.assertLessEqual(len(errors.getvalue().encode("utf-8")), 160)
                self.assertIn("evaluation blocked:", errors.getvalue())
                for label in (
                    "chatgpt_enterprise",
                    "restricted_worker",
                    "openshell_worker",
                    "verified_local",
                    "ready_for_human_decision",
                    "sensitive-candidate-version-canary",
                ):
                    self.assertNotIn(label, errors.getvalue())
        self.assertEqual(list(f.root.glob(".scorecard-*.tmp")), [])
        self.assertFalse((f.root / "scorecard.json").exists())

    def test_zero_run_draft_stdout_is_only_unlabeled_status(self) -> None:
        f = self.fixture
        args = [
            "--corpus",
            str(f.corpus_path),
            "--sources",
            str(f.sources_path),
            "--rubric",
            str(f.rubric_path),
            "--allow-incomplete",
        ]
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            self.assertEqual(main(args), 0)
        self.assertEqual(errors.getvalue(), "")
        self.assertEqual(
            json.loads(output.getvalue()),
            {
                "status_format_version": 1,
                "decision_readiness": "incomplete",
                "candidate_run_count": 0,
            },
        )
        for label in ("chatgpt_enterprise", "restricted_worker", "openshell_worker"):
            self.assertNotIn(label, output.getvalue())

    def test_cli_schema_error_never_echoes_private_candidate_field(self) -> None:
        f = self.fixture
        args = f.cli_args()
        candidate_path = f.root / f"candidate-{f.runs[0]['candidate_id']}.json"
        candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
        marker = "SYNTHETIC-PRIVATE-CONTENT-CANARY"
        candidate[marker] = "untrusted field"
        save(candidate_path, candidate)
        target = f.root / "schema-denied.json"
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            self.assertEqual(main([*args, "--output", str(target)]), 2)
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(
            errors.getvalue(),
            "evaluation blocked: invalid evaluation input or output\n",
        )
        self.assertNotIn(marker, errors.getvalue())
        self.assertFalse(target.exists())

    def test_cli_duplicate_key_error_never_echoes_private_field_or_path(self) -> None:
        f = self.fixture
        args = f.cli_args()
        candidate_path = f.root / f"candidate-{f.runs[0]['candidate_id']}.json"
        marker = "SYNTHETIC-PRIVATE-CONTENT-CANARY"
        candidate_path.write_text(f'{{"{marker}":0,"{marker}":1}}\n', encoding="utf-8")
        target = f.root / "duplicate-denied.json"
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            self.assertEqual(main([*args, "--output", str(target)]), 2)
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(
            errors.getvalue(),
            "evaluation blocked: invalid evaluation input or output\n",
        )
        self.assertNotIn(marker, errors.getvalue())
        self.assertNotIn(str(candidate_path), errors.getvalue())
        self.assertFalse(target.exists())

    def test_cli_argument_error_never_echoes_untrusted_value(self) -> None:
        f = self.fixture
        marker = "SYNTHETIC-PRIVATE-ARGUMENT-CANARY"
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            self.assertEqual(main(["--corpus", str(f.corpus_path), f"--{marker}"]), 2)
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(
            errors.getvalue(),
            "evaluation blocked: invalid evaluation input or output\n",
        )
        self.assertNotIn(marker, errors.getvalue())

    def test_invalid_signed_bundle_never_writes_scorecard_output(self) -> None:
        f = self.fixture
        run_paths = []
        for run in f.runs:
            path = f.root / f"candidate-{run['candidate_id']}.json"
            save(path, run)
            run_paths.append(str(path))
        f.witness_signature_path.write_bytes(b"invalid signature")
        target = f.root / "must-not-exist.json"
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            exit_code = main(
                [
                    "--corpus",
                    str(f.corpus_path),
                    "--sources",
                    str(f.sources_path),
                    "--rubric",
                    str(f.rubric_path),
                    "--runs",
                    *run_paths,
                    "--binding-manifest",
                    str(f.binding_path),
                    "--witness-key-sha256",
                    file_hash(f.witness_public_path),
                    "--witness-id",
                    "test-independent-freeze-witness",
                    "--control-key-sha256",
                    file_hash(f.control_public_path),
                    "--control-reviewer-id",
                    "test-independent-control-reviewer",
                    "--output",
                    str(target),
                ]
            )
        self.assertEqual(exit_code, 2)
        self.assertFalse(target.exists())

    def test_cli_output_never_overwrites_any_consumed_input(self) -> None:
        f = self.fixture
        args = f.cli_args()
        run_path = f.root / f"candidate-{f.runs[0]['candidate_id']}.json"
        for target in (
            f.corpus_path,
            f.sources_path,
            f.rubric_path,
            run_path,
            f.binding_path,
            f.map_path,
        ):
            with self.subTest(target=target.name):
                before = target.read_bytes()
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    self.assertEqual(main([*args, "--output", str(target)]), 2)
                self.assertEqual(target.read_bytes(), before)

    def test_cli_output_rejects_symlink_and_packet_directory(self) -> None:
        f = self.fixture
        args = f.cli_args()
        symlink = f.root / "scorecard-link.json"
        symlink.symlink_to(f.corpus_path)
        before = f.corpus_path.read_bytes()
        for target in (symlink, f.packet_dir / "scorecard.json"):
            with self.subTest(target=target.name):
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    self.assertEqual(main([*args, "--output", str(target)]), 2)
                self.assertEqual(f.corpus_path.read_bytes(), before)
        self.assertFalse((f.packet_dir / "scorecard.json").exists())

    def test_output_route_symlink_cannot_change_consumer_target_after_exit(
        self,
    ) -> None:
        f = self.fixture
        operator_root = f.root / "operator-output"
        private_parent = operator_root / "private"
        private_parent.mkdir(parents=True, mode=0o700)
        with tempfile.TemporaryDirectory(
            prefix="cr0011-consumer-route-", dir="/private/tmp"
        ) as public_name:
            public_root = Path(public_name)
            public_root.chmod(0o777)
            attacker_parent = public_root / "attacker" / "private"
            attacker_parent.mkdir(parents=True, mode=0o700)
            attacker_report = attacker_parent / "scorecard.json"
            attacker_report.write_text("attacker-controlled report", encoding="utf-8")
            route = public_root / "route"
            route.symlink_to(operator_root, target_is_directory=True)
            target = route / "private" / "scorecard.json"
            output, errors = io.StringIO(), io.StringIO()
            with redirect_stdout(output), redirect_stderr(errors):
                exit_code = main([*f.cli_args(), "--output", str(target)])
            route.unlink()
            route.symlink_to(public_root / "attacker", target_is_directory=True)
            self.assertEqual(
                target.read_text(encoding="utf-8"), "attacker-controlled report"
            )
            self.assertEqual(exit_code, 2)
            self.assertEqual(output.getvalue(), "")
            self.assertLessEqual(len(errors.getvalue().encode("utf-8")), 160)
            self.assertFalse((private_parent / "scorecard.json").exists())
            self.assertEqual(list(private_parent.glob(".scorecard-*.tmp")), [])

    def test_public_nonsticky_parent_cannot_replace_private_output_after_exit(
        self,
    ) -> None:
        f = self.fixture
        with tempfile.TemporaryDirectory(
            prefix="cr0011-public-parent-", dir="/private/tmp"
        ) as shared_name:
            shared = Path(shared_name)
            shared.chmod(0o777)
            private_parent = shared / "private"
            private_parent.mkdir(mode=0o700)
            target = private_parent / "scorecard.json"
            output, errors = io.StringIO(), io.StringIO()
            with redirect_stdout(output), redirect_stderr(errors):
                exit_code = main([*f.cli_args(), "--output", str(target)])
            retired_private = shared / "retired-private"
            private_parent.rename(retired_private)
            private_parent.mkdir(mode=0o700)
            target.write_text("forged replacement", encoding="utf-8")
            self.assertEqual(target.read_text(encoding="utf-8"), "forged replacement")
            self.assertEqual(exit_code, 2)
            self.assertEqual(output.getvalue(), "")
            self.assertLessEqual(len(errors.getvalue().encode("utf-8")), 160)
            self.assertFalse((retired_private / "scorecard.json").exists())
            self.assertEqual(list(retired_private.glob(".scorecard-*.tmp")), [])

    def test_root_owned_sticky_temp_parent_allows_private_fresh_output(self) -> None:
        f = self.fixture
        with tempfile.TemporaryDirectory(
            prefix="cr0011-private-output-", dir="/private/tmp"
        ) as private_name:
            target = Path(private_name).resolve(strict=True) / "scorecard.json"
            output, errors = io.StringIO(), io.StringIO()
            with redirect_stdout(output), redirect_stderr(errors):
                self.assertEqual(main([*f.cli_args(), "--output", str(target)]), 0)
            self.assertEqual(output.getvalue(), "")
            self.assertEqual(errors.getvalue(), "")
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertEqual(
                json.loads(target.read_text(encoding="utf-8"))["decision_readiness"],
                "ready_for_human_decision",
            )

    def test_untrusted_owner_before_private_root_cannot_control_output_entry(
        self,
    ) -> None:
        f = self.fixture
        with tempfile.TemporaryDirectory(
            prefix="cr0011-untrusted-owner-", dir="/private/tmp"
        ) as outer_name:
            outer = Path(outer_name).resolve(strict=True)
            outer.chmod(0o755)
            private_parent = outer / "private"
            private_parent.mkdir(mode=0o700)
            target = private_parent / "scorecard.json"
            original_lstat = Path.lstat

            def attacker_owned_lstat(path: Path, *args: Any, **kwargs: Any) -> Any:
                observed = original_lstat(path, *args, **kwargs)
                if path != outer:
                    return observed
                return SimpleNamespace(
                    st_dev=observed.st_dev,
                    st_ino=observed.st_ino,
                    st_mode=observed.st_mode,
                    st_uid=os.geteuid() + 1000,
                    st_mtime_ns=observed.st_mtime_ns,
                    st_ctime_ns=observed.st_ctime_ns,
                )

            output, errors = io.StringIO(), io.StringIO()
            with (
                patch.object(Path, "lstat", new=attacker_owned_lstat),
                redirect_stdout(output),
                redirect_stderr(errors),
            ):
                exit_code = main([*f.cli_args(), "--output", str(target)])
            self.assertEqual(exit_code, 2)
            self.assertEqual(output.getvalue(), "")
            self.assertFalse(target.exists())

    def test_cli_output_ancestor_a_b_a_switch_cannot_publish_into_packets(
        self,
    ) -> None:
        f = self.fixture
        attacker = f.root / "attacker-output"
        attacker.mkdir()
        benign_packets = f.root / "benign-output" / "packets"
        benign_packets.mkdir(parents=True)
        route = attacker / "route"
        route.symlink_to(benign_packets.parent, target_is_directory=True)
        target = route / "packets" / "scorecard.json"
        signed_hashes = {
            path: file_hash(path)
            for path in (f.binding_path, f.receipt_path, f.map_path)
        }
        original_open = os.open
        original_validate = scorecard_module._validate_output_target
        validated = False
        switched = False

        def mark_validated(*args: Any, **kwargs: Any) -> None:
            nonlocal validated
            original_validate(*args, **kwargs)
            validated = True

        def switch_before_parent_open(
            path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
            flags: int,
            *args: Any,
            **kwargs: Any,
        ) -> int:
            nonlocal switched
            if (
                validated
                and not switched
                and (path == target.parent or path == "packets")
            ):
                route.unlink()
                route.symlink_to(f.root, target_is_directory=True)
                switched = True
                try:
                    return original_open(path, flags, *args, **kwargs)
                finally:
                    route.unlink()
                    route.symlink_to(benign_packets.parent, target_is_directory=True)
            return original_open(path, flags, *args, **kwargs)

        with (
            patch("eval.scorecard._validate_output_target", side_effect=mark_validated),
            patch("eval.scorecard.os.open", side_effect=switch_before_parent_open),
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(main([*f.cli_args(), "--output", str(target)]), 2)
        # The symlink route is rejected before the old parent-open hook runs.
        self.assertFalse(switched)
        self.assertFalse((f.packet_dir / target.name).exists())
        self.assertFalse((benign_packets / target.name).exists())
        self.assertEqual(list(f.packet_dir.glob(".scorecard-*.tmp")), [])
        self.assertEqual(list(benign_packets.glob(".scorecard-*.tmp")), [])
        self.assertEqual(
            {path: file_hash(path) for path in signed_hashes}, signed_hashes
        )

    def test_cli_output_parent_rename_switch_cannot_publish_into_packets(self) -> None:
        f = self.fixture
        attacker = f.root / "attacker-output"
        attacker.mkdir()
        route = attacker / "route"
        benign_packets = route / "packets"
        benign_packets.mkdir(parents=True)
        parked_route = attacker / "route-parked"
        target = benign_packets / "scorecard.json"
        original_open = os.open
        original_validate = scorecard_module._validate_output_target
        validated = False
        switched = False

        def mark_validated(*args: Any, **kwargs: Any) -> None:
            nonlocal validated
            original_validate(*args, **kwargs)
            validated = True

        def rename_before_parent_open(
            path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
            flags: int,
            *args: Any,
            **kwargs: Any,
        ) -> int:
            nonlocal switched
            if (
                validated
                and not switched
                and (path == target.parent or path == "packets")
            ):
                route.rename(parked_route)
                route.symlink_to(f.root, target_is_directory=True)
                switched = True
                try:
                    return original_open(path, flags, *args, **kwargs)
                finally:
                    route.unlink()
                    parked_route.rename(route)
            return original_open(path, flags, *args, **kwargs)

        with (
            patch("eval.scorecard._validate_output_target", side_effect=mark_validated),
            patch("eval.scorecard.os.open", side_effect=rename_before_parent_open),
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(main([*f.cli_args(), "--output", str(target)]), 2)
        self.assertTrue(switched)
        self.assertFalse((f.packet_dir / target.name).exists())
        self.assertFalse(target.exists())
        self.assertEqual(list(f.packet_dir.glob(".scorecard-*.tmp")), [])
        self.assertEqual(list(benign_packets.glob(".scorecard-*.tmp")), [])

    def test_cli_output_parent_rename_after_link_rolls_back_held_file(self) -> None:
        f = self.fixture
        private_parent = f.root / "scorer-private"
        private_parent.mkdir(mode=0o700)
        parked_parent = f.root / "scorer-private-parked"
        target = private_parent / "scorecard.json"
        original_link = os.link
        switched = False

        def rename_after_link(source: str, destination: str, **kwargs: Any) -> None:
            nonlocal switched
            original_link(source, destination, **kwargs)
            if destination == target.name and not switched:
                private_parent.rename(parked_parent)
                private_parent.mkdir(mode=0o700)
                switched = True

        output, errors = io.StringIO(), io.StringIO()
        try:
            with (
                patch("eval.scorecard.os.link", side_effect=rename_after_link),
                redirect_stdout(output),
                redirect_stderr(errors),
            ):
                exit_code = main([*f.cli_args(), "--output", str(target)])
            self.assertTrue(switched)
            self.assertEqual(exit_code, 2)
            self.assertEqual(output.getvalue(), "")
            self.assertLessEqual(len(errors.getvalue().encode("utf-8")), 160)
            self.assertFalse(target.exists())
            self.assertFalse((parked_parent / target.name).exists())
            self.assertEqual(list(parked_parent.glob(".scorecard-*.tmp")), [])
            self.assertEqual(list(private_parent.glob(".scorecard-*.tmp")), [])
        finally:
            if switched:
                private_parent.rmdir()
                parked_parent.rename(private_parent)

    def test_cli_output_ancestor_switch_that_stays_in_packets_denies(self) -> None:
        f = self.fixture
        attacker = f.root / "attacker-output"
        attacker.mkdir()
        benign_packets = f.root / "benign-output" / "packets"
        benign_packets.mkdir(parents=True)
        route = attacker / "route"
        route.symlink_to(benign_packets.parent, target_is_directory=True)
        target = route / "packets" / "scorecard.json"
        original_open = os.open
        original_validate = scorecard_module._validate_output_target
        validated = False
        switched = False

        def mark_validated(*args: Any, **kwargs: Any) -> None:
            nonlocal validated
            original_validate(*args, **kwargs)
            validated = True

        def switch_before_parent_open(
            path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
            flags: int,
            *args: Any,
            **kwargs: Any,
        ) -> int:
            nonlocal switched
            if (
                validated
                and not switched
                and (path == target.parent or path == "packets")
            ):
                route.unlink()
                route.symlink_to(f.root, target_is_directory=True)
                switched = True
            return original_open(path, flags, *args, **kwargs)

        with (
            patch("eval.scorecard._validate_output_target", side_effect=mark_validated),
            patch("eval.scorecard.os.open", side_effect=switch_before_parent_open),
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(main([*f.cli_args(), "--output", str(target)]), 2)
        # The symlink route is rejected before the old parent-open hook runs.
        self.assertFalse(switched)
        self.assertFalse((f.packet_dir / target.name).exists())
        self.assertFalse((benign_packets / target.name).exists())
        self.assertEqual(list(f.packet_dir.glob(".scorecard-*.tmp")), [])
        self.assertEqual(list(benign_packets.glob(".scorecard-*.tmp")), [])

    def test_cli_nested_output_ancestor_symlink_switch_denies(self) -> None:
        f = self.fixture
        attacker = f.root / "attacker-output"
        attacker.mkdir()
        benign = f.root / "benign-output"
        benign_packets = benign / "allowed" / "packets"
        benign_packets.mkdir(parents=True)
        outer = attacker / "outer"
        inner = benign / "inner"
        outer.symlink_to(benign, target_is_directory=True)
        inner.symlink_to(benign / "allowed", target_is_directory=True)
        target = outer / "inner" / "packets" / "scorecard.json"
        original_open = os.open
        original_validate = scorecard_module._validate_output_target
        validated = False
        switched = False

        def mark_validated(*args: Any, **kwargs: Any) -> None:
            nonlocal validated
            original_validate(*args, **kwargs)
            validated = True

        def switch_inner_before_parent_open(
            path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
            flags: int,
            *args: Any,
            **kwargs: Any,
        ) -> int:
            nonlocal switched
            if (
                validated
                and not switched
                and (path == target.parent or path == "packets")
            ):
                inner.unlink()
                inner.symlink_to(f.root, target_is_directory=True)
                switched = True
            return original_open(path, flags, *args, **kwargs)

        with (
            patch("eval.scorecard._validate_output_target", side_effect=mark_validated),
            patch(
                "eval.scorecard.os.open", side_effect=switch_inner_before_parent_open
            ),
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(main([*f.cli_args(), "--output", str(target)]), 2)
        # Both nested symlink components are rejected before the hook runs.
        self.assertFalse(switched)
        self.assertFalse((f.packet_dir / target.name).exists())
        self.assertFalse((benign_packets / target.name).exists())

    def test_cli_catalog_a_b_a_switch_never_publishes_in_verified_packet_dir(
        self,
    ) -> None:
        f = self.fixture
        second_packet_dir = f.root / "packets-second-valid-bundle"
        shutil.copytree(f.packet_dir, second_packet_dir)
        catalog_a, raw_a = binding_module._read_json(
            f.binding_path, binding_module.MAX_RECEIPT_BYTES, "binding manifest"
        )
        catalog_b = {**catalog_a, "packet_directory": str(second_packet_dir)}
        raw_b = json.dumps(catalog_b, sort_keys=True).encode()
        second_catalog = f.root / "binding-second.json"
        save(second_catalog, catalog_b)
        self.assertEqual(
            build_scorecard(
                f.corpus,
                f.sources,
                f.rubric,
                f.runs,
                binding_manifest_path=second_catalog,
                witness_key_sha256=file_hash(f.witness_public_path),
                witness_id="test-independent-freeze-witness",
                control_key_sha256=file_hash(f.control_public_path),
                control_reviewer_id="test-independent-control-reviewer",
            )["decision_readiness"],
            "ready_for_human_decision",
        )
        target = second_packet_dir / "scorecard.json"
        reads = iter(((catalog_a, raw_a), (catalog_b, raw_b), (catalog_a, raw_a)))
        original_read_json = binding_module._read_json

        def switched_catalog(
            path: Path, limit: int, label: str
        ) -> tuple[dict[str, Any], bytes]:
            if path == f.binding_path:
                return next(reads)
            return original_read_json(path, limit, label)

        with (
            patch("eval.binding._read_json", side_effect=switched_catalog),
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(main([*f.cli_args(), "--output", str(target)]), 2)
        self.assertFalse(target.exists())

    def test_cli_catalog_byte_change_with_same_paths_denies_publication(self) -> None:
        f = self.fixture
        catalog, raw = binding_module._read_json(
            f.binding_path, binding_module.MAX_RECEIPT_BYTES, "binding manifest"
        )
        changed_raw = json.dumps(catalog, separators=(",", ":")).encode()
        self.assertNotEqual(raw, changed_raw)
        reads = iter(((catalog, raw), (catalog, changed_raw), (catalog, raw)))
        original_read_json = binding_module._read_json

        def switched_bytes(
            path: Path, limit: int, label: str
        ) -> tuple[dict[str, Any], bytes]:
            if path == f.binding_path:
                return next(reads)
            return original_read_json(path, limit, label)

        target = f.root / "scorecard-after-catalog-byte-change.json"
        with (
            patch("eval.binding._read_json", side_effect=switched_bytes),
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(main([*f.cli_args(), "--output", str(target)]), 2)
        self.assertFalse(target.exists())

    def test_cli_catalog_change_that_stays_changed_denies_publication(self) -> None:
        f = self.fixture
        second_packet_dir = f.root / "packets-second"
        shutil.copytree(f.packet_dir, second_packet_dir)
        catalog_a, raw_a = binding_module._read_json(
            f.binding_path, binding_module.MAX_RECEIPT_BYTES, "binding manifest"
        )
        catalog_b = {**catalog_a, "packet_directory": str(second_packet_dir)}
        raw_b = json.dumps(catalog_b, sort_keys=True).encode()
        reads = iter(((catalog_a, raw_a), (catalog_b, raw_b), (catalog_b, raw_b)))
        original_read_json = binding_module._read_json

        def changed_catalog(
            path: Path, limit: int, label: str
        ) -> tuple[dict[str, Any], bytes]:
            if path == f.binding_path:
                return next(reads)
            return original_read_json(path, limit, label)

        target = f.root / "scorecard-after-changed-catalog.json"
        with (
            patch("eval.binding._read_json", side_effect=changed_catalog),
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(main([*f.cli_args(), "--output", str(target)]), 2)
        self.assertFalse(target.exists())

    def test_cli_packet_path_resolution_a_b_a_switch_denies_publication(self) -> None:
        f = self.fixture
        second_packet_dir = f.root / "packets-second"
        shutil.copytree(f.packet_dir, second_packet_dir)
        alias_parent = f.root / "packet-alias-parent"
        alias_parent.mkdir()
        packet_alias = alias_parent / "selected-packets"
        packet_alias.symlink_to(f.packet_dir, target_is_directory=True)
        catalog = json.loads(f.binding_path.read_text(encoding="utf-8"))
        save(f.binding_path, {**catalog, "packet_directory": str(packet_alias)})
        reads = 0
        original_read_json = binding_module._read_json

        def switched_resolution(
            path: Path, limit: int, label: str
        ) -> tuple[dict[str, Any], bytes]:
            nonlocal reads
            if path == f.binding_path:
                reads += 1
                if reads in (2, 3):
                    packet_alias.unlink()
                    packet_alias.symlink_to(
                        second_packet_dir if reads == 2 else f.packet_dir,
                        target_is_directory=True,
                    )
            return original_read_json(path, limit, label)

        target = second_packet_dir / "scorecard.json"
        with (
            patch("eval.binding._read_json", side_effect=switched_resolution),
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(main([*f.cli_args(), "--output", str(target)]), 2)
        self.assertFalse(target.exists())

    def test_cli_static_other_signed_packet_directory_is_excluded(self) -> None:
        f = self.fixture
        second_packet_dir = f.root / "packets-second"
        shutil.copytree(f.packet_dir, second_packet_dir)
        catalog = json.loads(f.binding_path.read_text(encoding="utf-8"))
        save(f.binding_path, {**catalog, "packet_directory": str(second_packet_dir)})
        target = second_packet_dir / "scorecard.json"
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(main([*f.cli_args(), "--output", str(target)]), 2)
        self.assertFalse(target.exists())

    def test_cli_verifier_packet_directory_switch_cannot_publish_into_it(self) -> None:
        f = self.fixture
        second_packet_dir = f.root / "packets-second-valid-bundle"
        shutil.copytree(f.packet_dir, second_packet_dir)
        target = second_packet_dir / "scorecard.json"
        original_manifest = blind_tool_module._packet_manifest
        switched = False

        def selected_other_packet_directory(
            packet_dir: Path, *args: Any, **kwargs: Any
        ) -> Any:
            nonlocal switched
            if packet_dir == f.packet_dir.resolve():
                packet_dir = second_packet_dir
                switched = True
            return original_manifest(packet_dir, *args, **kwargs)

        with (
            patch(
                "eval.blind_review.tool._packet_manifest",
                side_effect=selected_other_packet_directory,
            ),
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(main([*f.cli_args(), "--output", str(target)]), 2)
        self.assertTrue(switched)
        self.assertFalse(target.exists())
        self.assertEqual(list(second_packet_dir.glob(".scorecard-*.tmp")), [])

    def test_callable_verifier_packet_directory_switch_cannot_claim_ready(self) -> None:
        f = self.fixture
        second_packet_dir = f.root / "packets-second-valid-bundle"
        shutil.copytree(f.packet_dir, second_packet_dir)
        original_manifest = blind_tool_module._packet_manifest
        switched = False

        def selected_other_packet_directory(
            packet_dir: Path, *args: Any, **kwargs: Any
        ) -> Any:
            nonlocal switched
            if packet_dir == f.packet_dir.resolve():
                packet_dir = second_packet_dir
                switched = True
            return original_manifest(packet_dir, *args, **kwargs)

        with (
            patch(
                "eval.blind_review.tool._packet_manifest",
                side_effect=selected_other_packet_directory,
            ),
            self.assertRaises(EvaluationError),
        ):
            f.score()
        self.assertTrue(switched)

    def test_cli_packet_path_rename_a_b_a_during_verification_denies(self) -> None:
        f = self.fixture
        with tempfile.TemporaryDirectory() as second_root_name:
            second_root = Path(second_root_name).resolve(strict=True)
            second_packet_dir = second_root / "packets"
            shutil.copytree(f.packet_dir, second_packet_dir)
            target = second_packet_dir / "scorecard.json"
            parked_root = f.root.with_name(f"{f.root.name}-parked")
            original_manifest = blind_tool_module._packet_manifest
            switched = False

            def switched_packet_path(
                packet_dir: Path, *args: Any, **kwargs: Any
            ) -> Any:
                nonlocal switched
                if packet_dir != f.packet_dir.resolve() or switched:
                    return original_manifest(packet_dir, *args, **kwargs)
                switched = True
                f.root.rename(parked_root)
                f.root.symlink_to(second_root, target_is_directory=True)
                try:
                    return original_manifest(packet_dir, *args, **kwargs)
                finally:
                    f.root.unlink()
                    parked_root.rename(f.root)

            with (
                patch(
                    "eval.blind_review.tool._packet_manifest",
                    side_effect=switched_packet_path,
                ),
                redirect_stdout(io.StringIO()),
                redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(main([*f.cli_args(), "--output", str(target)]), 2)
            self.assertTrue(switched)
            self.assertFalse(target.exists())
            self.assertEqual(list(second_packet_dir.glob(".scorecard-*.tmp")), [])

    def test_cli_packet_path_switch_that_stays_on_b_denies(self) -> None:
        f = self.fixture
        with tempfile.TemporaryDirectory() as second_root_name:
            second_root = Path(second_root_name).resolve(strict=True)
            second_packet_dir = second_root / "packets"
            shutil.copytree(f.packet_dir, second_packet_dir)
            target = second_packet_dir / "scorecard.json"
            parked_root = f.root.with_name(f"{f.root.name}-parked")
            original_manifest = blind_tool_module._packet_manifest
            args = [*f.cli_args(), "--output", str(target)]
            switched = False

            def switched_packet_path(
                packet_dir: Path, *args: Any, **kwargs: Any
            ) -> Any:
                nonlocal switched
                if packet_dir == f.packet_dir.resolve() and not switched:
                    switched = True
                    f.root.rename(parked_root)
                    f.root.symlink_to(second_root, target_is_directory=True)
                return original_manifest(packet_dir, *args, **kwargs)

            try:
                with (
                    patch(
                        "eval.blind_review.tool._packet_manifest",
                        side_effect=switched_packet_path,
                    ),
                    redirect_stdout(io.StringIO()),
                    redirect_stderr(io.StringIO()),
                ):
                    self.assertEqual(main(args), 2)
            finally:
                if f.root.is_symlink():
                    f.root.unlink()
                    parked_root.rename(f.root)
            self.assertTrue(switched)
            self.assertFalse(target.exists())
            self.assertEqual(list(second_packet_dir.glob(".scorecard-*.tmp")), [])

    def test_cli_output_is_fresh_exclusive_and_bound_to_this_invocation(self) -> None:
        f = self.fixture
        args = f.cli_args()
        target = f.root / "fresh-scorecard.json"
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(main([*args, "--output", str(target)]), 0)
        self.assertEqual(
            json.loads(target.read_text())["decision_readiness"],
            "ready_for_human_decision",
        )
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        before = target.read_bytes()
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(main([*args, "--output", str(target)]), 2)
        self.assertEqual(target.read_bytes(), before)
        f.witness_signature_path.write_bytes(b"invalid signature")
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(main([*args, "--output", str(target)]), 2)
        self.assertEqual(target.read_bytes(), before)
        self.assertEqual(list(f.root.glob(".scorecard-*.tmp")), [])

    def test_output_route_is_pinned_before_alias_validation(self) -> None:
        f = self.fixture
        safe_root = f.root / "safe-output-root"
        old_review_root = f.root / "old-review-output"
        (safe_root / "private").mkdir(parents=True, mode=0o700)
        (old_review_root / "private").mkdir(parents=True, mode=0o700)
        attacker = f.root / "attacker-output"
        attacker.mkdir()
        route = attacker / "route"
        route.symlink_to(safe_root, target_is_directory=True)
        target = route / "private" / "scorecard.json"
        original_validate = scorecard_module._validate_output_target
        switched = False

        def switch_after_validation(*args: Any) -> None:
            nonlocal switched
            original_validate(*args)
            route.unlink()
            route.symlink_to(old_review_root, target_is_directory=True)
            switched = True

        try:
            with (
                patch(
                    "eval.scorecard._validate_output_target",
                    side_effect=switch_after_validation,
                ),
                redirect_stdout(io.StringIO()),
                redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(main([*f.cli_args(), "--output", str(target)]), 2)
        finally:
            if route.is_symlink():
                route.unlink()
                route.symlink_to(safe_root, target_is_directory=True)
        # The symlink route is rejected before alias validation is reached.
        self.assertFalse(switched)
        self.assertFalse((safe_root / "private" / "scorecard.json").exists())
        self.assertFalse((old_review_root / "private" / "scorecard.json").exists())
        self.assertEqual(
            list((old_review_root / "private").glob(".scorecard-*.tmp")), []
        )

    def test_private_lexical_route_cannot_escape_to_public_canonical_parent(
        self,
    ) -> None:
        f = self.fixture
        with tempfile.TemporaryDirectory(
            prefix="cr0011-public-output-", dir="/private/tmp"
        ) as public_name:
            public_root = Path(public_name)
            public_parent = public_root / "real"
            public_parent.mkdir()
            public_root.chmod(0o777)
            public_parent.chmod(0o777)
            bridge = f.root / "bridge"
            bridge.symlink_to(public_root, target_is_directory=True)
            target = bridge / "real" / "scorecard.json"
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(main([*f.cli_args(), "--output", str(target)]), 2)
            self.assertFalse((public_parent / "scorecard.json").exists())
            self.assertEqual(list(public_parent.glob(".scorecard-*.tmp")), [])

    def test_existing_ready_path_rejects_new_successful_attempt(self) -> None:
        f = self.fixture
        args = f.cli_args()
        target = f.root / "stale-ready.json"
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(main([*args, "--output", str(target)]), 0)
        before = target.read_bytes()
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(main([*args, "--output", str(target)]), 2)
        self.assertEqual(target.read_bytes(), before)

    def test_output_link_collision_leaves_no_partial_scorecard(self) -> None:
        f = self.fixture
        target = f.root / "link-collision.json"
        with (
            patch("eval.scorecard.os.link", side_effect=FileExistsError),
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(main([*f.cli_args(), "--output", str(target)]), 2)
        self.assertFalse(target.exists())
        self.assertEqual(list(f.root.glob(".scorecard-*.tmp")), [])

    def test_replaced_temporary_output_cannot_be_published_as_scorecard(self) -> None:
        f = self.fixture
        target = f.root / "temp-replaced.json"
        replacement = b"unowned temporary replacement"
        original_link = os.link
        replaced_name: str | None = None

        def replace_source_before_link(
            source: str,
            destination: str,
            **kwargs: Any,
        ) -> None:
            nonlocal replaced_name
            if source.startswith(".scorecard-"):
                directory_fd = kwargs["src_dir_fd"]
                os.unlink(source, dir_fd=directory_fd)
                descriptor = os.open(
                    source,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=directory_fd,
                )
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(replacement)
                replaced_name = source
            original_link(source, destination, **kwargs)

        with (
            patch("eval.scorecard.os.link", side_effect=replace_source_before_link),
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(main([*f.cli_args(), "--output", str(target)]), 2)
        self.assertIsNotNone(replaced_name)
        self.assertEqual(target.read_bytes(), replacement)
        assert replaced_name is not None
        self.assertEqual((f.root / replaced_name).read_bytes(), replacement)

    def test_failed_directory_sync_preserves_replaced_output_inode(self) -> None:
        f = self.fixture
        target = f.root / "published-replaced.json"
        replacement = b"unowned published replacement"
        original_fsync = os.fsync
        replaced = False

        def replace_before_directory_sync(descriptor: int) -> None:
            nonlocal replaced
            if (
                not replaced
                and stat.S_ISDIR(os.fstat(descriptor).st_mode)
                and target.exists()
            ):
                target.unlink()
                target.write_bytes(replacement)
                replaced = True
                raise OSError("synthetic directory sync failure")
            original_fsync(descriptor)

        with (
            patch("eval.scorecard.os.fsync", side_effect=replace_before_directory_sync),
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(main([*f.cli_args(), "--output", str(target)]), 2)
        self.assertTrue(replaced)
        self.assertEqual(target.read_bytes(), replacement)
        self.assertEqual(list(f.root.glob(".scorecard-*.tmp")), [])
