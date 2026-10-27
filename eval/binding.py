"""Reverify signed blind and independent control bytes before scorecard readiness.

The local checks bind assertions to signed artifacts. They cannot establish that a
tenant really emitted an event or that the signers had independent custody.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eval.blind_review.tool import (
    MAX_RECEIPT_BYTES,
    BlindReviewError,
    _absolute,
    _exact,
    _id,
    _object,
    _read_json,
    verify_signed_bundle,
)
from eval.scorecard import EvaluationError, canonical_digest

BINDING_PATH_FIELDS = frozenset(
    {
        "approved_corpus_path",
        "approved_sources_path",
        "approved_rubric_path",
        "raw_observations_path",
        "packet_directory",
        "candidate_map_path",
        "blind_reviews_path",
        "witness_receipt_path",
        "witness_signature_path",
        "witness_public_key_path",
        "control_review_path",
        "control_signature_path",
        "control_public_key_path",
    }
)


@dataclass(frozen=True, slots=True)
class BindingCatalog:
    """One immutable catalog read and its resolved artifact path selection."""

    manifest_path: Path
    manifest_resolved_path: Path
    raw: bytes
    paths: tuple[tuple[str, Path], ...]
    resolved_paths: tuple[tuple[str, Path], ...]
    file_stamp: tuple[int, int, int, int, int, int]
    parent_stamp: tuple[int, int, int, int, int, int]
    packet_directory_stamp: tuple[int, int, int, int, int, int]
    packet_parent_stamp: tuple[int, int, int, int, int, int]


def _stamp(path: Path) -> tuple[int, int, int, int, int, int]:
    try:
        observed = path.lstat()
    except OSError as exc:
        raise BlindReviewError("binding catalog path is unavailable") from exc
    return (
        observed.st_dev,
        observed.st_ino,
        observed.st_mode,
        observed.st_size,
        observed.st_mtime_ns,
        observed.st_ctime_ns,
    )


def capture_binding_catalog(manifest_path: Path) -> BindingCatalog:
    """Freeze exact catalog bytes and resolved paths before any signed read."""
    file_before, parent_before = _stamp(manifest_path), _stamp(manifest_path.parent)
    try:
        manifest_resolved_before = manifest_path.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise BlindReviewError("binding manifest path cannot be resolved") from exc
    manifest, raw = _read_json(manifest_path, MAX_RECEIPT_BYTES, "binding manifest")
    file_after, parent_after = _stamp(manifest_path), _stamp(manifest_path.parent)
    try:
        manifest_resolved_after = manifest_path.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise BlindReviewError("binding manifest path cannot be resolved") from exc
    if (file_before, parent_before) != (
        file_after,
        parent_after,
    ) or manifest_resolved_before != manifest_resolved_after:
        raise BlindReviewError("binding manifest changed while being read")
    _exact(
        manifest,
        {"schema_version", *BINDING_PATH_FIELDS},
        "binding manifest",
    )
    if manifest.get("schema_version") != 2:
        raise BlindReviewError("unsupported binding manifest version")
    paths: list[tuple[str, Path]] = []
    resolved: list[tuple[str, Path]] = []
    for field in sorted(BINDING_PATH_FIELDS):
        value = manifest.get(field)
        if not isinstance(value, str) or not value:
            raise BlindReviewError("binding manifest needs absolute artifact paths")
        path = _absolute(Path(value), field)
        if field != "packet_directory" and path.is_symlink():
            raise BlindReviewError("binding artifact file cannot be a symlink")
        try:
            resolved_path = path.resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise BlindReviewError("binding artifact path cannot be resolved") from exc
        paths.append((field, path))
        resolved.append((field, resolved_path))
    packet_directory = dict(resolved)["packet_directory"]
    return BindingCatalog(
        manifest_path=manifest_path,
        manifest_resolved_path=manifest_resolved_after,
        raw=raw,
        paths=tuple(paths),
        resolved_paths=tuple(resolved),
        file_stamp=file_after,
        parent_stamp=parent_after,
        packet_directory_stamp=_stamp(packet_directory),
        packet_parent_stamp=_stamp(packet_directory.parent),
    )


def assert_binding_catalog_current(
    catalog: BindingCatalog, *, allow_parent_write: bool = False
) -> None:
    """Deny raw-byte, inode, or path-resolution drift from the chosen catalog."""
    current = capture_binding_catalog(catalog.manifest_path)
    if (
        current.manifest_path != catalog.manifest_path
        or current.manifest_resolved_path != catalog.manifest_resolved_path
        or current.raw != catalog.raw
        or current.paths != catalog.paths
        or current.resolved_paths != catalog.resolved_paths
        or current.file_stamp != catalog.file_stamp
        or current.packet_directory_stamp != catalog.packet_directory_stamp
        or (not allow_parent_write and current.parent_stamp != catalog.parent_stamp)
        or (
            not allow_parent_write
            and current.packet_parent_stamp != catalog.packet_parent_stamp
        )
    ):
        raise BlindReviewError("binding manifest changed during evaluation")


def _control_observations(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    expected: dict[str, dict[str, Any]] = {}
    if "permission_probe" in result:
        expected["forbidden_probe"] = result["permission_probe"]
    if "allowed_probe" in result:
        expected["allowed_probe"] = result["allowed_probe"]
    transition = result.get("revocation_transition")
    if transition is not None:
        expected["revocation_pre_probe"] = transition["pre_probe"]
        expected["revocation_acknowledgement"] = transition["acknowledgement"]
        expected["revocation_post_probe"] = transition["post_probe"]
    return expected


def verify_binding(
    corpus: dict[str, Any],
    sources: dict[str, Any],
    rubric: dict[str, Any],
    candidate_runs: list[dict[str, Any]],
    *,
    binding_manifest_path: Path,
    witness_key_sha256: str,
    witness_id: str,
    control_key_sha256: str,
    control_reviewer_id: str,
    binding_catalog: BindingCatalog | None = None,
    packet_directory_fd: int | None = None,
) -> dict[str, Any]:
    """Return a local binding summary only after every exact comparison passes."""
    try:
        catalog = binding_catalog or capture_binding_catalog(binding_manifest_path)
        if catalog.manifest_path != binding_manifest_path:
            raise BlindReviewError("binding catalog path differs from scorer")
        assert_binding_catalog_current(catalog)
        paths = dict(catalog.resolved_paths)
        for field, expected in (
            ("approved_corpus_path", corpus),
            ("approved_sources_path", sources),
            ("approved_rubric_path", rubric),
        ):
            observed, _ = _read_json(paths[field], MAX_RECEIPT_BYTES * 128, field)
            if canonical_digest(observed) != canonical_digest(expected):
                raise BlindReviewError("binding approved input differs from scorer")
        bundle = verify_signed_bundle(
            corpus_path=paths["approved_corpus_path"],
            sources_path=paths["approved_sources_path"],
            rubric_path=paths["approved_rubric_path"],
            raw_observations_path=paths["raw_observations_path"],
            packet_dir=paths["packet_directory"],
            map_path=paths["candidate_map_path"],
            reviews_path=paths["blind_reviews_path"],
            receipt_path=paths["witness_receipt_path"],
            signature_path=paths["witness_signature_path"],
            public_key_path=paths["witness_public_key_path"],
            trusted_key_sha256=witness_key_sha256,
            expected_witness_id=witness_id,
            control_review_path=paths["control_review_path"],
            control_signature_path=paths["control_signature_path"],
            control_public_key_path=paths["control_public_key_path"],
            trusted_control_key_sha256=control_key_sha256,
            expected_control_reviewer_id=control_reviewer_id,
            packet_directory_fd=packet_directory_fd,
            expected_packet_directory_identity=(
                catalog.packet_directory_stamp[0],
                catalog.packet_directory_stamp[1],
            ),
        )
        for field, expected in (
            ("corpus_digest", corpus),
            ("source_pack_digest", sources),
            ("rubric_digest", rubric),
        ):
            if bundle["approved_digests"][field] != canonical_digest(expected):
                raise BlindReviewError("signed approved inputs differ from scorer")
        assignments = bundle["concealed_map"]["assignments"]
        assignment_by_pair = {
            (item["candidate_id"], item["case_id"]): item for item in assignments
        }
        disposition_by_pair = {
            (item["candidate_id"], item["case_id"]): item
            for item in bundle["concealed_map"]["dispositions"]
        }
        signed_pairs = set(assignment_by_pair) | set(disposition_by_pair)
        control = bundle["control_review"]
        control_by_pair = {
            (item["candidate_id"], item["case_id"]): item for item in control["cases"]
        }
        raw_by_pair: dict[tuple[str, str], dict[str, Any]] = {}
        for raw_value in bundle["raw_observations"]["observations"]:
            raw = _object(raw_value, "raw observation")
            pair = (
                _id(raw.get("candidate_id"), "raw candidate ID"),
                _id(raw.get("case_id"), "raw case ID"),
            )
            if pair not in signed_pairs or pair in raw_by_pair:
                raise BlindReviewError("raw observation identity is invalid")
            if raw.get("status") == "completed":
                assignment = assignment_by_pair.get(pair)
                if assignment is None or raw.get("run_id") != assignment["run_id"]:
                    raise BlindReviewError(
                        "raw observation run differs from signed map"
                    )
            elif raw != disposition_by_pair.get(pair):
                raise BlindReviewError("raw disposition differs from signed map")
            raw_by_pair[pair] = raw
        if set(raw_by_pair) != signed_pairs:
            raise BlindReviewError("raw observation matrix is incomplete")
        runs_by_id = {run["candidate_id"]: run for run in candidate_runs}
        if set(runs_by_id) != bundle["candidates"] or len(runs_by_id) != len(
            candidate_runs
        ):
            raise BlindReviewError("candidate-run set differs from frozen matrix")
        if control["candidate_run_digests"] != {
            candidate_id: canonical_digest(run)
            for candidate_id, run in runs_by_id.items()
        }:
            raise BlindReviewError("candidate-run bytes differ from control freeze")
        for candidate_id, run in runs_by_id.items():
            result_by_case = {result["case_id"]: result for result in run["results"]}
            if len(result_by_case) != len(run["results"]) or set(result_by_case) != set(
                bundle["cases"]
            ):
                raise BlindReviewError("candidate results differ from frozen matrix")
            for case_id, result_value in result_by_case.items():
                result = _object(result_value, "candidate result")
                pair = (candidate_id, case_id)
                control_case = control_by_pair[pair]
                if result.get("status") != "completed":
                    disposition = disposition_by_pair.get(pair)
                    if (
                        disposition is None
                        or result.get("status") != disposition["status"]
                        or result.get("reason") != disposition["reason"]
                        or control_case["status"] != disposition["status"]
                        or control_case["reason"] != disposition["reason"]
                    ):
                        raise BlindReviewError(
                            "candidate disposition differs from freeze"
                        )
                    continue
                assignment = assignment_by_pair.get(pair)
                if assignment is None:
                    raise BlindReviewError("completed result lacks signed packet")
                packet = bundle["packets_by_id"][assignment["packet_id"]]
                blind_review = bundle["reviews_by_packet"][assignment["packet_id"]][0]
                for run_field, map_field in (
                    ("run_id", "run_id"),
                    ("answer_artifact_ref", "answer_artifact_ref"),
                    ("latency_ms", "latency_ms"),
                    ("cost_usd", "cost_usd"),
                    ("user_effort_minutes", "user_effort_minutes"),
                ):
                    if result.get(run_field) != assignment[map_field]:
                        raise BlindReviewError(
                            "candidate result differs from signed map"
                        )
                if (
                    run.get("candidate_version") != assignment["candidate_version"]
                    or run.get("source_delivery") != assignment["source_delivery"]
                    or result.get("citations")
                    != [
                        {"evidence_id": span["evidence_id"], "quote": span["quote"]}
                        for span in packet["citation_spans"]
                    ]
                ):
                    raise BlindReviewError("candidate delivery or citations differ")
                review = _object(result.get("review"), "candidate quality review")
                for field in ("reviewer_id", "reviewed_at", "scores"):
                    if review.get(field) != blind_review[field]:
                        raise BlindReviewError("candidate quality review changed")
                if review.get("notes", "") != blind_review["notes"]:
                    raise BlindReviewError("candidate quality review notes changed")
                if (
                    result.get("observed_behavior") != control_case["observed_behavior"]
                    or review.get("permission_violation")
                    != control_case["permission_violation"]
                    or review.get("prompt_injection_violation")
                    != control_case["prompt_injection_violation"]
                ):
                    raise BlindReviewError("candidate control review fields changed")
                expected_events = _control_observations(result)
                actual_events = {
                    item["kind"]: item["observation"]
                    for item in control_case["permission_events"]
                }
                if actual_events != expected_events:
                    raise BlindReviewError(
                        "candidate probes differ from control review"
                    )
                if (
                    control_case["raw_answer_sha256"]
                    != raw_by_pair[pair]["screening"]["raw_answer_sha256"]
                    or control_case["raw_run_artifact"]["ref"]
                    != result["answer_artifact_ref"]
                ):
                    raise BlindReviewError("candidate raw run differs from control")
        assembly = bundle["assembly"]
        assert_binding_catalog_current(catalog)
        return {
            "status": "verified_local",
            "cell_count": assembly["cell_count"],
            "packet_count": assembly["packet_count"],
            "disposition_count": assembly["disposition_count"],
            "packet_manifest_sha256": assembly["packet_manifest_sha256"],
            "candidate_map_sha256": assembly["candidate_map_sha256"],
            "blind_reviews_sha256": assembly["reviews_sha256"],
            "control_review_sha256": assembly["control_review_sha256"],
            "control_signature_sha256": assembly["control_signature_sha256"],
            "witness_receipt_sha256": assembly["witness_receipt_sha256"],
            "raw_observations_sha256": assembly["raw_observations_sha256"],
            "witness_id": witness_id,
            "control_reviewer_id": control_reviewer_id,
            "witness_public_key_sha256": witness_key_sha256,
            "control_public_key_sha256": control_key_sha256,
        }
    except (BlindReviewError, KeyError, TypeError, ValueError) as exc:
        raise EvaluationError("signed scorer binding was rejected") from exc
