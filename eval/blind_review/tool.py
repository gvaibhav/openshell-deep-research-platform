"""Offline packet preparation and externally witnessed blind review verification."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import secrets
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from eval.scorecard import DIMENSIONS as SCORE_DIMENSIONS
from eval.scorecard import (
    EvaluationError,
    _assert_output_target,
    _attach_packet_directory,
    _close_output_target,
    _CreatedFile,
    _directory_identity,
    _open_output_target,
    _OutputTarget,
    _reject_packet_directory_ancestor,
    _unlink_if_same_file,
    _write_new_output,
    build_scorecard,
)

MAX_INPUT_BYTES = 1024 * 1024
MAX_PACKET_BYTES = 128 * 1024
MAX_PACKET_COUNT = 128
MAX_CELL_COUNT = 240
MAX_SOURCE_COUNT = 64
MAX_ALLOWED_SOURCES = 16
MAX_SOURCE_TEXT = 4096
MAX_ANSWER = 20000
MAX_CITATIONS = 32
MAX_REVIEWS = 640
MAX_RECEIPT_BYTES = 8192
MAX_VERIFIER_BYTES = 8 * 1024 * 1024
TRUSTED_VERIFIER_PATH = Path("/usr/bin/openssl")
# macOS root-owned /usr/bin/openssl, LibreSSL 3.3.6, qualified on 2026-10-26.
TRUSTED_VERIFIER_SHA256 = (
    "49db04c17e3a8c169ebc48a1149d78c165a86c04913203f46b2a14ce7f4a14fc"
)
ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
PACKET_ID_RE = re.compile(r"bp-[0-9a-f]{32}\Z")
DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
TIMESTAMP_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})\Z"
)
CANDIDATE_ALIASES = {
    "chatgpt_enterprise": ("chatgpt",),
    "restricted_worker": ("restricted worker",),
    "openshell_worker": ("openshell",),
}


class BlindReviewError(ValueError):
    """An input or artifact cannot support a blind review claim."""


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise BlindReviewError("invalid JSON value") from exc


def _encoded_file(value: Any) -> bytes:
    return _canonical_bytes(value) + b"\n"


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    found: dict[str, Any] = {}
    for key, value in pairs:
        if key in found:
            raise BlindReviewError("duplicate JSON key")
        found[key] = value
    return found


def _reject_constant(_: str) -> Any:
    raise BlindReviewError("nonfinite JSON number")


def _parse_json(raw: bytes) -> Any:
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_no_duplicate_keys,
            parse_constant=_reject_constant,
        )
        _canonical_bytes(value)  # Reject unpaired surrogates before output.
        return value
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise BlindReviewError("invalid UTF-8 JSON") from exc


def _absolute(path: Path, label: str) -> Path:
    if not path.is_absolute():
        raise BlindReviewError(f"{label} must be an absolute path")
    return path


def _read_regular(path: Path, limit: int, label: str) -> bytes:
    _absolute(path, label)
    try:
        with os.fdopen(
            os.open(
                path,
                os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            ),
            "rb",
        ) as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise BlindReviewError(f"{label} must be a regular file")
            raw = handle.read(limit + 1)
        if len(raw) > limit:
            raise BlindReviewError(f"{label} exceeds its byte bound")
        return raw
    except OSError as exc:
        raise BlindReviewError(f"{label} is unavailable") from exc


def _read_json(path: Path, limit: int, label: str) -> tuple[dict[str, Any], bytes]:
    raw = _read_regular(path, limit, label)
    return _object(_parse_json(raw), label), raw


def _read_json_at(
    directory_fd: int, name: str, limit: int, label: str
) -> tuple[dict[str, Any], bytes]:
    """Read one packet child from the already selected directory inode."""
    if not name or name in (".", "..") or "/" in name:
        raise BlindReviewError("packet child name is invalid")
    try:
        with os.fdopen(
            os.open(
                name,
                os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
                dir_fd=directory_fd,
            ),
            "rb",
        ) as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise BlindReviewError(f"{label} must be a regular file")
            raw = handle.read(limit + 1)
    except OSError as exc:
        raise BlindReviewError(f"{label} is unavailable") from exc
    if len(raw) > limit:
        raise BlindReviewError(f"{label} exceeds its byte bound")
    return _object(_parse_json(raw), label), raw


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BlindReviewError(f"{label} must be an object")
    return value


def _exact(value: dict[str, Any], keys: set[str], label: str) -> None:
    if set(value) != keys:
        raise BlindReviewError(f"{label} has missing or unsupported fields")


def _array(value: Any, label: str, minimum: int, maximum: int) -> list[Any]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise BlindReviewError(f"{label} has an invalid array size")
    return value


def _count(value: Any, label: str, minimum: int, maximum: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise BlindReviewError(f"{label} is outside its count bound")
    return value


def _text(value: Any, label: str, maximum: int, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > maximum:
        raise BlindReviewError(f"{label} must be bounded text")
    if not allow_empty and not value.strip():
        raise BlindReviewError(f"{label} must be nonempty text")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise BlindReviewError(f"{label} contains invalid Unicode") from exc
    return value


def _id(value: Any, label: str) -> str:
    identifier = _text(value, label, 128)
    if ID_RE.fullmatch(identifier) is None:
        raise BlindReviewError(f"{label} has invalid syntax")
    return identifier


def _packet_id(value: Any) -> str:
    identifier = _text(value, "packet ID", 35)
    if PACKET_ID_RE.fullmatch(identifier) is None:
        raise BlindReviewError("packet ID has invalid syntax")
    return identifier


def _sha256(value: Any, label: str) -> str:
    candidate = _text(value, label, 64)
    if DIGEST_RE.fullmatch(candidate) is None:
        raise BlindReviewError(f"{label} is not SHA-256")
    return candidate


def _timestamp(value: Any, label: str) -> datetime:
    value = _text(value, label, 40)
    if TIMESTAMP_RE.fullmatch(value) is None:
        raise BlindReviewError(f"{label} needs an offset")
    try:
        instant = datetime.fromisoformat(value)
    except ValueError as exc:
        raise BlindReviewError(f"{label} is invalid") from exc
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise BlindReviewError(f"{label} needs an offset")
    return instant


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BlindReviewError(f"{label} must be a number")
    try:
        number = float(value)
    except OverflowError as exc:
        raise BlindReviewError(f"{label} must be nonnegative and finite") from exc
    if not math.isfinite(number) or number < 0:
        raise BlindReviewError(f"{label} must be nonnegative and finite")
    return number


def _approved(value: Any, label: str) -> datetime:
    approval = _object(value, f"{label} approval")
    _exact(approval, {"status", "reviewer_id", "reviewed_at"}, f"{label} approval")
    if approval.get("status") != "approved":
        raise BlindReviewError(f"{label} is not approved")
    _id(approval.get("reviewer_id"), f"{label} reviewer")
    return _timestamp(approval.get("reviewed_at"), f"{label} approval time")


def _ids(value: Any, label: str, *, minimum: int, maximum: int) -> list[str]:
    items = [_id(item, label) for item in _array(value, label, minimum, maximum)]
    if len(items) != len(set(items)):
        raise BlindReviewError(f"{label} contains duplicate IDs")
    return items


def _load_approved_inputs(
    corpus_path: Path, sources_path: Path, rubric_path: Path
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    set[str],
    dict[str, str],
    datetime,
]:
    corpus, _ = _read_json(corpus_path, MAX_INPUT_BYTES, "corpus")
    pack, _ = _read_json(sources_path, MAX_INPUT_BYTES, "source pack")
    rubric, _ = _read_json(rubric_path, MAX_INPUT_BYTES, "rubric")
    try:
        build_scorecard(corpus, pack, rubric, [])
    except Exception as exc:
        raise BlindReviewError("shared evaluator preflight rejected inputs") from exc
    if corpus.get("schema_version") != 1 or pack.get("schema_version") != 1:
        raise BlindReviewError("unsupported corpus or source version")
    if rubric.get("schema_version", 1) != 1:
        raise BlindReviewError("unsupported rubric version")
    approved_at = max(
        _approved(corpus.get("approval"), "corpus"),
        _approved(rubric.get("approval"), "rubric"),
    )
    if corpus.get("source_pack_id") != pack.get("source_pack_id"):
        raise BlindReviewError("source-pack identity mismatch")
    if _sha256(corpus.get("source_pack_digest"), "corpus source digest") != _digest(
        pack
    ):
        raise BlindReviewError("source-pack digest mismatch")
    sources: dict[str, dict[str, Any]] = {}
    for source_value in _array(pack.get("sources"), "source pack", 1, MAX_SOURCE_COUNT):
        source = _object(source_value, "source")
        _exact(source, {"evidence_id", "data_class", "origin", "text"}, "source")
        source_id = _id(source.get("evidence_id"), "evidence ID")
        if source_id in sources:
            raise BlindReviewError("duplicate source ID")
        if source.get("data_class") not in ("public", "synthetic"):
            raise BlindReviewError("source class is not public or synthetic")
        _text(source.get("origin"), "source origin", 256)
        _text(source.get("text"), "source text", MAX_SOURCE_TEXT)
        sources[source_id] = source
    cases: dict[str, dict[str, Any]] = {}
    for case_value in _array(corpus.get("cases"), "corpus cases", 20, 30):
        case = _object(case_value, "case")
        case_id = _id(case.get("case_id"), "case ID")
        if case_id in cases:
            raise BlindReviewError("duplicate case ID")
        if case.get("data_class") not in ("public", "synthetic"):
            raise BlindReviewError("case class is not public or synthetic")
        _text(case.get("question"), "case question", 4096)
        allowed = _ids(
            case.get("allowed_evidence_ids"),
            "allowed evidence",
            minimum=1,
            maximum=MAX_ALLOWED_SOURCES,
        )
        forbidden = _ids(
            case.get("forbidden_evidence_ids"),
            "forbidden evidence",
            minimum=0,
            maximum=MAX_SOURCE_COUNT,
        )
        if not set(allowed).isdisjoint(forbidden):
            raise BlindReviewError("case source permission overlap")
        if any(source_id not in sources for source_id in allowed + forbidden):
            raise BlindReviewError("case references a missing source")
        cases[case_id] = case
    candidates = set(
        _ids(
            rubric.get("required_candidates"),
            "required candidate",
            minimum=1,
            maximum=8,
        )
    )
    digests = {
        "corpus_digest": _digest(corpus),
        "source_pack_digest": _digest(pack),
        "rubric_digest": _digest(rubric),
    }
    return cases, sources, candidates, digests, approved_at


def _answer_is_within_view(
    raw_answer: str,
    packet_answer: str,
    allowed: set[str],
    sources: dict[str, dict[str, Any]],
    identity_markers: list[str],
) -> None:
    folded = packet_answer.casefold()
    for marker in identity_markers:
        if len(marker) >= 4 and marker.casefold() in folded:
            raise BlindReviewError("packet answer exposes candidate identity")
    for source_id, source in sources.items():
        if source_id in allowed:
            continue
        source_text = source["text"]
        if source_text and source_text in raw_answer:
            raise BlindReviewError("raw answer contains unadmitted source text")
        if source_text and source_text in packet_answer:
            raise BlindReviewError("packet answer contains unadmitted source text")
        if source_id.casefold() in folded:
            raise BlindReviewError("packet answer names an unadmitted source")


def _packet_for_observation(
    value: Any,
    cases: dict[str, dict[str, Any]],
    sources: dict[str, dict[str, Any]],
    candidates: set[str],
    approved_at: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    observation = _object(value, "observation")
    _exact(
        observation,
        {
            "status",
            "case_id",
            "candidate_id",
            "run_id",
            "candidate_version",
            "model_version",
            "source_delivery",
            "answer_artifact_ref",
            "latency_ms",
            "cost_usd",
            "user_effort_minutes",
            "raw_answer",
            "packet_answer",
            "screening",
            "citations",
        },
        "observation",
    )
    if observation.get("status") != "completed":
        raise BlindReviewError("completed observation status is invalid")
    case_id = _id(observation.get("case_id"), "case ID")
    candidate_id = _id(observation.get("candidate_id"), "candidate ID")
    run_id = _id(observation.get("run_id"), "run ID")
    if case_id not in cases or candidate_id not in candidates:
        raise BlindReviewError(
            "observation is outside approved case or candidate scope"
        )
    case = cases[case_id]
    allowed_list = _ids(
        case.get("allowed_evidence_ids"),
        "allowed evidence",
        minimum=1,
        maximum=MAX_ALLOWED_SOURCES,
    )
    allowed = set(allowed_list)
    candidate_version = _text(
        observation.get("candidate_version"), "candidate version", 256
    )
    model_version = _text(observation.get("model_version"), "model version", 256)
    source_delivery = _text(observation.get("source_delivery"), "source delivery", 256)
    answer_artifact_ref = _text(
        observation.get("answer_artifact_ref"), "answer artifact reference", 256
    )
    raw_answer = _text(observation.get("raw_answer"), "raw answer", MAX_ANSWER)
    packet_answer = _text(observation.get("packet_answer"), "packet answer", MAX_ANSWER)
    raw_answer_bytes = raw_answer.encode("utf-8")
    packet_answer_bytes = packet_answer.encode("utf-8")
    if raw_answer_bytes != packet_answer_bytes:
        raise BlindReviewError("screened packet answer differs from raw answer")
    latency_ms = _number(observation.get("latency_ms"), "latency")
    cost_usd = _number(observation.get("cost_usd"), "cost")
    user_effort_minutes = _number(observation.get("user_effort_minutes"), "user effort")
    screening = _object(observation.get("screening"), "screening")
    _exact(
        screening,
        {
            "custodian_id",
            "screened_at",
            "record_ref",
            "raw_answer_sha256",
            "packet_answer_sha256",
        },
        "screening",
    )
    _id(screening.get("custodian_id"), "screening custodian")
    screened_at = _timestamp(screening.get("screened_at"), "screening time")
    if screened_at < approved_at:
        raise BlindReviewError("screening preceded corpus or rubric approval")
    _text(screening.get("record_ref"), "screening record reference", 256)
    if _sha256(screening.get("raw_answer_sha256"), "raw answer digest") != _hash(
        raw_answer_bytes
    ):
        raise BlindReviewError("raw answer screening digest mismatch")
    if _sha256(screening.get("packet_answer_sha256"), "packet answer digest") != _hash(
        packet_answer_bytes
    ):
        raise BlindReviewError("packet answer screening digest mismatch")
    identity_markers = [
        candidate_id,
        candidate_id.replace("_", " "),
        candidate_version,
        model_version,
        *CANDIDATE_ALIASES.get(candidate_id, ()),
    ]
    _answer_is_within_view(
        raw_answer, packet_answer, allowed, sources, identity_markers
    )

    citation_spans: list[dict[str, Any]] = []
    seen_citations: set[tuple[str, int, int]] = set()
    for item in _array(observation.get("citations"), "citations", 0, MAX_CITATIONS):
        citation = _object(item, "citation")
        _exact(citation, {"evidence_id", "quote", "start", "end"}, "citation")
        evidence_id = _id(citation.get("evidence_id"), "citation evidence ID")
        if evidence_id not in allowed:
            raise BlindReviewError("citation is outside approved source view")
        source_text = sources[evidence_id]["text"]
        quote = _text(citation.get("quote"), "citation quote", MAX_SOURCE_TEXT)
        start, end = citation.get("start"), citation.get("end")
        if (
            isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, int)
            or not isinstance(end, int)
            or not 0 <= start < end <= len(source_text)
            or source_text[start:end] != quote
        ):
            raise BlindReviewError("citation span does not match visible source")
        key = (evidence_id, start, end)
        if key in seen_citations:
            raise BlindReviewError("duplicate citation span")
        seen_citations.add(key)
        citation_spans.append(
            {"evidence_id": evidence_id, "quote": quote, "start": start, "end": end}
        )

    packet_id = "bp-" + secrets.token_hex(16)
    packet = {
        "schema_version": 1,
        "packet_id": packet_id,
        "case_id": case_id,
        "question": case["question"],
        "answer": packet_answer,
        "source_snapshots": [
            {
                "evidence_id": source_id,
                "origin": sources[source_id]["origin"],
                "text": sources[source_id]["text"],
            }
            for source_id in allowed_list
        ],
        "citation_spans": citation_spans,
    }
    if len(_encoded_file(packet)) > MAX_PACKET_BYTES:
        raise BlindReviewError("packet exceeds its byte bound")
    concealed = {
        "status": "completed",
        "packet_id": packet_id,
        "case_id": case_id,
        "candidate_id": candidate_id,
        "run_id": run_id,
        "candidate_version": candidate_version,
        "model_version": model_version,
        "source_delivery": source_delivery,
        "answer_artifact_ref": answer_artifact_ref,
        "latency_ms": latency_ms,
        "cost_usd": cost_usd,
        "user_effort_minutes": user_effort_minutes,
        "screening": screening,
    }
    return packet, concealed


def _disposition_for_observation(
    value: Any,
    cases: dict[str, dict[str, Any]],
    candidates: set[str],
) -> dict[str, Any]:
    disposition = _object(value, "noncompleted disposition")
    _exact(
        disposition,
        {"case_id", "candidate_id", "status", "reason", "disposition_evidence"},
        "noncompleted disposition",
    )
    case_id = _id(disposition.get("case_id"), "disposition case ID")
    candidate_id = _id(disposition.get("candidate_id"), "disposition candidate ID")
    if case_id not in cases or candidate_id not in candidates:
        raise BlindReviewError("disposition is outside approved candidate/case scope")
    if disposition.get("status") not in ("deferred", "failed"):
        raise BlindReviewError("noncompleted disposition status is invalid")
    return {
        "case_id": case_id,
        "candidate_id": candidate_id,
        "status": disposition["status"],
        "reason": _text(disposition.get("reason"), "disposition reason", 2048),
        "disposition_evidence": _control_artifact(
            disposition.get("disposition_evidence"), "disposition evidence"
        ),
    }


def _validate_prepare_paths(
    corpus_path: Path,
    sources_path: Path,
    rubric_path: Path,
    observations_path: Path,
    packet_dir: Path,
    map_path: Path,
) -> None:
    for label, path in (
        ("corpus", corpus_path),
        ("sources", sources_path),
        ("rubric", rubric_path),
        ("observations", observations_path),
        ("packet directory", packet_dir),
        ("candidate map", map_path),
    ):
        _absolute(path, label)
    resolved_packets = packet_dir.resolve()
    resolved_map = map_path.resolve()
    if (
        resolved_map.is_relative_to(resolved_packets)
        or resolved_packets.is_relative_to(resolved_map.parent)
        or packet_dir.exists()
        or map_path.exists()
        or packet_dir.is_symlink()
        or map_path.is_symlink()
    ):
        raise BlindReviewError(
            "reviewer packets and concealed map need separate new paths"
        )
    if resolved_map in {
        corpus_path.resolve(),
        sources_path.resolve(),
        rubric_path.resolve(),
        observations_path.resolve(),
    }:
        raise BlindReviewError("candidate map collides with an input")


def _write_exclusive(path: Path, raw: bytes, mode: int) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, mode)
        try:
            os.fchmod(fd, mode)
            with os.fdopen(fd, "wb", closefd=False) as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(fd)
        finally:
            os.close(fd)
    except OSError as exc:
        raise BlindReviewError("could not create exclusive output artifact") from exc


def _private_directory(path: Path) -> None:
    try:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        metadata = path.lstat()
        if not stat.S_ISDIR(metadata.st_mode):
            raise BlindReviewError("private output parent is not a directory")
        if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o700:
            raise BlindReviewError("private output parent needs owner-only access")
    except OSError as exc:
        raise BlindReviewError("private output parent is unavailable") from exc


def _require_private_directory_fd(directory_fd: int) -> None:
    metadata = os.fstat(directory_fd)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise BlindReviewError("private output parent needs owner-only access")


@dataclass(frozen=True, slots=True)
class _PreparationRoutePin:
    path: Path
    resolved: Path
    components: tuple[tuple[Path, tuple[int, int, int, int, int, int]], ...]


def _preparation_route_pin(path: Path) -> _PreparationRoutePin:
    """Pin the operator's initial route, including existing symlink identities."""
    _absolute(path, "preparation parent")
    if ".." in path.parts:
        raise BlindReviewError("preparation parent has a noncanonical component")
    current = Path("/")
    components: list[tuple[Path, tuple[int, int, int, int, int, int]]] = []
    try:
        resolved = path.resolve(strict=False)
        for part in path.parts:
            if part != "/":
                current = current / part
            try:
                metadata = current.lstat()
            except FileNotFoundError:
                break
            components.append(
                (
                    current,
                    (
                        metadata.st_dev,
                        metadata.st_ino,
                        metadata.st_mode,
                        metadata.st_uid,
                        metadata.st_mtime_ns,
                        metadata.st_ctime_ns,
                    ),
                )
            )
    except (OSError, RuntimeError) as exc:
        raise BlindReviewError("preparation parent route is unavailable") from exc
    pin = _PreparationRoutePin(path, resolved, tuple(components))
    _assert_preparation_route_pin(pin)
    return pin


def _assert_preparation_route_pin(pin: _PreparationRoutePin) -> None:
    try:
        if pin.path.resolve(strict=False) != pin.resolved:
            raise BlindReviewError("preparation parent route changed")
        for path, expected in pin.components:
            metadata = path.lstat()
            observed = (
                metadata.st_dev,
                metadata.st_ino,
                metadata.st_mode,
                metadata.st_uid,
                metadata.st_mtime_ns,
                metadata.st_ctime_ns,
            )
            if observed[:4] != expected[:4] or (
                stat.S_ISLNK(expected[2]) and observed != expected
            ):
                raise BlindReviewError("preparation parent route changed")
    except (OSError, RuntimeError) as exc:
        raise BlindReviewError("preparation parent route changed") from exc


def _assert_pinned_preparation_target(
    target: _OutputTarget, pin: _PreparationRoutePin
) -> None:
    _assert_preparation_route_pin(pin)
    if target.path.parent != pin.path or target.route.resolved_parent != pin.resolved:
        raise BlindReviewError("preparation target differs from initial route")


def _write_exclusive_at(directory_fd: int, name: str, raw: bytes) -> _CreatedFile:
    """Write a packet artifact; caller owns its handle through final validation."""
    if not name or name in (".", "..") or "/" in name:
        raise BlindReviewError("packet artifact name is invalid")
    descriptor: int | None = None
    identity: tuple[int, int] | None = None
    try:
        descriptor = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory_fd,
        )
        identity = _directory_identity(descriptor)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(raw)
            handle.flush()
        os.fsync(descriptor)
        created = _CreatedFile(descriptor)
        descriptor = None
        return created
    except OSError as exc:
        raise BlindReviewError("packet artifact could not be written") from exc
    finally:
        if descriptor is not None:
            try:
                if identity is not None:
                    _unlink_if_same_file(directory_fd, name, identity)
            finally:
                os.close(descriptor)


def _assert_created_packet_directory(
    packet_target: _OutputTarget, packet_directory_fd: int
) -> None:
    """Check the requested packet name still reaches the newly opened inode."""
    _assert_output_target(packet_target, parent_was_written=True, require_fresh=False)
    expected = _directory_identity(packet_directory_fd)
    for metadata in (
        os.stat(
            packet_target.path.name,
            dir_fd=packet_target.directory_fd,
            follow_symlinks=False,
        ),
        packet_target.path.lstat(),
    ):
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or (metadata.st_dev, metadata.st_ino) != expected
        ):
            raise BlindReviewError("packet directory identity changed")


def _cleanup_created_packets(
    packet_target: _OutputTarget | None,
    packet_directory_fd: int,
    created_identity: tuple[int, int] | None,
    created_files: list[tuple[str, _CreatedFile]],
) -> None:
    """Never recursively remove a path chosen through a mutable ancestor."""
    if packet_target is None or created_identity is None:
        return
    if (
        packet_directory_fd >= 0
        and _directory_identity(packet_directory_fd) == created_identity
    ):
        for name, created in reversed(created_files):
            _unlink_if_same_file(packet_directory_fd, name, created.identity)
    try:
        observed = os.stat(
            packet_target.path.name,
            dir_fd=packet_target.directory_fd,
            follow_symlinks=False,
        )
        if (
            stat.S_ISDIR(observed.st_mode)
            and (
                observed.st_dev,
                observed.st_ino,
            )
            == created_identity
        ):
            os.rmdir(packet_target.path.name, dir_fd=packet_target.directory_fd)
    except OSError:
        # A moved or nonempty directory is left for operator reconciliation.
        pass


def prepare_packets(
    *,
    corpus_path: Path,
    sources_path: Path,
    rubric_path: Path,
    observations_path: Path,
    packet_dir: Path,
    map_path: Path,
) -> dict[str, Any]:
    """Write allowlisted anonymous packets and a separately private identity map."""
    map_parent_pin = _preparation_route_pin(map_path.parent)
    packet_parent_pin = _preparation_route_pin(packet_dir.parent)
    _validate_prepare_paths(
        corpus_path, sources_path, rubric_path, observations_path, packet_dir, map_path
    )
    _assert_preparation_route_pin(map_parent_pin)
    _assert_preparation_route_pin(packet_parent_pin)
    cases, sources, candidates, digests, approved_at = _load_approved_inputs(
        corpus_path, sources_path, rubric_path
    )
    observations, _ = _read_json(observations_path, MAX_INPUT_BYTES, "observations")
    _exact(
        observations,
        {
            "schema_version",
            "cell_count",
            "corpus_digest",
            "source_pack_digest",
            "rubric_digest",
            "observations",
        },
        "observations",
    )
    if observations.get("schema_version") != 2:
        raise BlindReviewError("unsupported observation version")
    for name, expected in digests.items():
        if _sha256(observations.get(name), name) != expected:
            raise BlindReviewError("observation input digest mismatch")
    cell_count = observations.get("cell_count")
    if (
        isinstance(cell_count, bool)
        or not isinstance(cell_count, int)
        or not 1 <= cell_count <= MAX_CELL_COUNT
    ):
        raise BlindReviewError("observation cell count is invalid")
    raw_items = _array(
        observations.get("observations"), "observations", cell_count, cell_count
    )
    packets: list[dict[str, Any]] = []
    assignments: list[dict[str, Any]] = []
    dispositions: list[dict[str, Any]] = []
    seen_case_candidate: set[tuple[str, str]] = set()
    seen_run_ids: set[str] = set()
    for item in raw_items:
        observation = _object(item, "observation")
        if observation.get("status") == "completed":
            packet, assignment = _packet_for_observation(
                observation, cases, sources, candidates, approved_at
            )
            case_candidate = (assignment["case_id"], assignment["candidate_id"])
            if assignment["run_id"] in seen_run_ids:
                raise BlindReviewError("duplicate candidate run ID")
            seen_run_ids.add(assignment["run_id"])
            packets.append(packet)
            assignments.append(assignment)
        else:
            disposition = _disposition_for_observation(observation, cases, candidates)
            case_candidate = (disposition["case_id"], disposition["candidate_id"])
            dispositions.append(disposition)
        if case_candidate in seen_case_candidate:
            raise BlindReviewError("duplicate candidate case cell")
        seen_case_candidate.add(case_candidate)
    if len(packets) > MAX_PACKET_COUNT:
        raise BlindReviewError("completed packet count exceeds its bound")
    paired = list(zip(packets, assignments, strict=True))
    secrets.SystemRandom().shuffle(paired)
    packet_records: list[dict[str, str]] = []
    for packet, assignment in paired:
        packet_sha256 = _hash(_encoded_file(packet))
        packet_records.append(
            {"packet_id": packet["packet_id"], "packet_sha256": packet_sha256}
        )
        assignment["packet_sha256"] = packet_sha256
    manifest = {
        "schema_version": 2,
        "cell_count": cell_count,
        "packet_count": len(packet_records),
        **digests,
        "packets": packet_records,
    }
    manifest_raw = _encoded_file(manifest)
    concealed_map = {
        "schema_version": 2,
        "cell_count": cell_count,
        "packet_count": len(packet_records),
        "packet_manifest_sha256": _hash(manifest_raw),
        **digests,
        "assignments": [assignment for _, assignment in paired],
        "dispositions": dispositions,
    }
    map_raw = _encoded_file(concealed_map)
    if len(map_raw) > MAX_INPUT_BYTES:
        raise BlindReviewError("concealed map exceeds its byte bound")

    _assert_preparation_route_pin(map_parent_pin)
    _assert_preparation_route_pin(packet_parent_pin)
    _private_directory(map_path.parent)
    _assert_preparation_route_pin(map_parent_pin)
    _assert_preparation_route_pin(packet_parent_pin)
    map_target: _OutputTarget | None = None
    packet_target: _OutputTarget | None = None
    packet_fd = -1
    packet_identity: tuple[int, int] | None = None
    packet_confirmed = False
    map_file: _CreatedFile | None = None
    created_files: list[tuple[str, _CreatedFile]] = []
    try:
        map_target = _open_output_target(
            map_path,
            [corpus_path, sources_path, rubric_path, observations_path, packet_dir],
            [],
        )
        _assert_pinned_preparation_target(map_target, map_parent_pin)
        _require_private_directory_fd(map_target.directory_fd)
        packet_target = _open_output_target(
            packet_dir,
            [corpus_path, sources_path, rubric_path, observations_path, map_path],
            [],
        )
        _assert_pinned_preparation_target(packet_target, packet_parent_pin)
        _reject_packet_directory_ancestor(
            packet_target.directory_fd, (map_target.directory_fd,)
        )
        os.mkdir(packet_dir.name, mode=0o700, dir_fd=packet_target.directory_fd)
        created_metadata = os.stat(
            packet_dir.name,
            dir_fd=packet_target.directory_fd,
            follow_symlinks=False,
        )
        if not stat.S_ISDIR(created_metadata.st_mode):
            raise BlindReviewError("new packet directory identity changed")
        packet_identity = (created_metadata.st_dev, created_metadata.st_ino)
        packet_fd = os.open(
            packet_dir.name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=packet_target.directory_fd,
        )
        if _directory_identity(packet_fd) != packet_identity:
            raise BlindReviewError("new packet directory identity changed")
        _assert_created_packet_directory(packet_target, packet_fd)
        packet_confirmed = True
        os.fchmod(packet_fd, 0o700)
        _reject_packet_directory_ancestor(packet_fd, (map_target.directory_fd,))
        for packet, _ in paired:
            name = f"{packet['packet_id']}.json"
            created_files.append(
                (name, _write_exclusive_at(packet_fd, name, _encoded_file(packet)))
            )
        created_files.append(
            (
                "packet-manifest.json",
                _write_exclusive_at(packet_fd, "packet-manifest.json", manifest_raw),
            )
        )
        os.fsync(packet_fd)
        _assert_created_packet_directory(packet_target, packet_fd)
        _assert_pinned_preparation_target(map_target, map_parent_pin)
        _assert_pinned_preparation_target(packet_target, packet_parent_pin)
        map_target = _attach_packet_directory(map_target, packet_dir, packet_fd)
        map_file = _write_new_output(map_target, map_raw)
        _assert_output_target(map_target, parent_was_written=True, require_fresh=False)
        _assert_created_packet_directory(packet_target, packet_fd)
        _assert_pinned_preparation_target(map_target, map_parent_pin)
        _assert_pinned_preparation_target(packet_target, packet_parent_pin)
        map_metadata = os.stat(
            map_path.name,
            dir_fd=map_target.directory_fd,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(map_metadata.st_mode)
            or (map_metadata.st_dev, map_metadata.st_ino) != map_file.identity
        ):
            raise BlindReviewError("concealed map identity changed")
        for name, created in created_files:
            metadata = os.stat(name, dir_fd=packet_fd, follow_symlinks=False)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or (metadata.st_dev, metadata.st_ino) != created.identity
            ):
                raise BlindReviewError("created packet artifact identity changed")
    except (OSError, BlindReviewError, EvaluationError) as exc:
        if map_target is not None and map_file is not None:
            _unlink_if_same_file(
                map_target.directory_fd, map_path.name, map_file.identity
            )
        _cleanup_created_packets(
            packet_target,
            packet_fd,
            packet_identity if packet_confirmed else None,
            created_files,
        )
        raise BlindReviewError("packet artifacts could not be written") from exc
    finally:
        if map_file is not None:
            map_file.close()
        for _, created in created_files:
            created.close()
        if packet_fd >= 0:
            os.close(packet_fd)
        if packet_target is not None:
            _close_output_target(packet_target)
        if map_target is not None:
            _close_output_target(map_target)
    return manifest


def _validate_packet(
    packet: dict[str, Any],
    packet_id: str,
    cases: dict[str, dict[str, Any]],
    sources: dict[str, dict[str, Any]],
) -> str:
    _exact(
        packet,
        {
            "schema_version",
            "packet_id",
            "case_id",
            "question",
            "answer",
            "source_snapshots",
            "citation_spans",
        },
        "packet",
    )
    if packet.get("schema_version") != 1 or packet.get("packet_id") != packet_id:
        raise BlindReviewError("packet identity mismatch")
    case_id = _id(packet.get("case_id"), "packet case ID")
    if case_id not in cases:
        raise BlindReviewError("packet case is outside approved corpus")
    if (
        _text(packet.get("question"), "packet question", 4096)
        != cases[case_id]["question"]
    ):
        raise BlindReviewError("packet question differs from approved corpus")
    _text(packet.get("answer"), "packet answer", MAX_ANSWER)
    source_texts: dict[str, str] = {}
    packet_sources = _array(
        packet.get("source_snapshots"), "packet sources", 1, MAX_ALLOWED_SOURCES
    )
    for item in packet_sources:
        source = _object(item, "packet source")
        _exact(source, {"evidence_id", "origin", "text"}, "packet source")
        source_id = _id(source.get("evidence_id"), "packet source ID")
        if source_id in source_texts:
            raise BlindReviewError("duplicate packet source")
        _text(source.get("origin"), "packet source origin", 256)
        source_texts[source_id] = _text(
            source.get("text"), "packet source text", MAX_SOURCE_TEXT
        )
    expected_sources = [
        {
            "evidence_id": source_id,
            "origin": sources[source_id]["origin"],
            "text": sources[source_id]["text"],
        }
        for source_id in cases[case_id]["allowed_evidence_ids"]
    ]
    if packet_sources != expected_sources:
        raise BlindReviewError("packet sources differ from approved case view")
    seen_spans: set[tuple[str, int, int]] = set()
    for item in _array(
        packet.get("citation_spans"), "packet citations", 0, MAX_CITATIONS
    ):
        citation = _object(item, "packet citation")
        _exact(citation, {"evidence_id", "quote", "start", "end"}, "packet citation")
        source_id = _id(citation.get("evidence_id"), "packet citation ID")
        if source_id not in source_texts:
            raise BlindReviewError("packet citation is outside visible sources")
        start, end = citation.get("start"), citation.get("end")
        quote = _text(citation.get("quote"), "packet citation quote", MAX_SOURCE_TEXT)
        if (
            isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, int)
            or not isinstance(end, int)
            or not 0 <= start < end <= len(source_texts[source_id])
            or source_texts[source_id][start:end] != quote
        ):
            raise BlindReviewError("packet citation span mismatch")
        key = (source_id, start, end)
        if key in seen_spans:
            raise BlindReviewError("duplicate packet citation")
        seen_spans.add(key)
    return case_id


def _packet_manifest(
    packet_dir: Path,
    cases: dict[str, dict[str, Any]],
    sources: dict[str, dict[str, Any]],
    approved_digests: dict[str, str],
    *,
    packet_directory_fd: int | None = None,
    expected_packet_directory_identity: tuple[int, int] | None = None,
) -> tuple[
    dict[str, Any], bytes, dict[str, str], dict[str, str], dict[str, dict[str, Any]]
]:
    _absolute(packet_dir, "packet directory")
    try:
        metadata = packet_dir.lstat()
        parent_metadata = packet_dir.parent.lstat()
    except OSError as exc:
        raise BlindReviewError("packet directory is unavailable") from exc
    if not stat.S_ISDIR(metadata.st_mode):
        raise BlindReviewError("packet directory must be a real directory")
    directory_stamp = (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )
    parent_stamp = (
        parent_metadata.st_dev,
        parent_metadata.st_ino,
        parent_metadata.st_mode,
        parent_metadata.st_mtime_ns,
        parent_metadata.st_ctime_ns,
    )
    try:
        selected_fd = (
            os.dup(packet_directory_fd)
            if packet_directory_fd is not None
            else os.open(
                packet_dir,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | os.O_NOFOLLOW
                | getattr(os, "O_CLOEXEC", 0),
            )
        )
    except OSError as exc:
        raise BlindReviewError("packet directory cannot be opened") from exc
    try:
        selected_metadata = os.fstat(selected_fd)
        if not stat.S_ISDIR(selected_metadata.st_mode) or (
            selected_metadata.st_dev,
            selected_metadata.st_ino,
        ) != (metadata.st_dev, metadata.st_ino):
            raise BlindReviewError("packet directory differs from held verifier inode")
        if (
            expected_packet_directory_identity is not None
            and (
                selected_metadata.st_dev,
                selected_metadata.st_ino,
            )
            != expected_packet_directory_identity
        ):
            raise BlindReviewError("packet directory differs from scorer catalog")
        return _packet_manifest_from_fd(
            packet_dir,
            selected_fd,
            cases,
            sources,
            approved_digests,
            directory_stamp,
            parent_stamp,
        )
    finally:
        os.close(selected_fd)


def _packet_manifest_from_fd(
    packet_dir: Path,
    directory_fd: int,
    cases: dict[str, dict[str, Any]],
    sources: dict[str, dict[str, Any]],
    approved_digests: dict[str, str],
    directory_stamp: tuple[int, int, int, int, int],
    parent_stamp: tuple[int, int, int, int, int],
) -> tuple[
    dict[str, Any], bytes, dict[str, str], dict[str, str], dict[str, dict[str, Any]]
]:
    manifest, raw = _read_json_at(
        directory_fd, "packet-manifest.json", MAX_INPUT_BYTES, "packet manifest"
    )
    _exact(
        manifest,
        {
            "schema_version",
            "cell_count",
            "packet_count",
            "corpus_digest",
            "source_pack_digest",
            "rubric_digest",
            "packets",
        },
        "packet manifest",
    )
    if manifest.get("schema_version") != 2:
        raise BlindReviewError("unsupported packet manifest version")
    cell_count = _count(manifest.get("cell_count"), "manifest cells", 1, MAX_CELL_COUNT)
    packet_count = _count(
        manifest.get("packet_count"), "manifest packets", 0, MAX_PACKET_COUNT
    )
    if packet_count > cell_count:
        raise BlindReviewError("packet count exceeds cell count")
    for field, expected in approved_digests.items():
        if _sha256(manifest.get(field), field) != expected:
            raise BlindReviewError("packet manifest differs from approved inputs")
    records = _array(
        manifest.get("packets"), "packet records", packet_count, packet_count
    )
    if packet_count != len(records):
        raise BlindReviewError("packet count mismatch")
    packet_cases: dict[str, str] = {}
    packet_answers: dict[str, str] = {}
    packets_by_id: dict[str, dict[str, Any]] = {}
    for item in records:
        record = _object(item, "packet record")
        _exact(record, {"packet_id", "packet_sha256"}, "packet record")
        packet_id = _packet_id(record.get("packet_id"))
        if packet_id in packet_cases:
            raise BlindReviewError("duplicate packet ID")
        expected_hash = _sha256(record.get("packet_sha256"), "packet digest")
        packet, packet_raw = _read_json_at(
            directory_fd, f"{packet_id}.json", MAX_PACKET_BYTES, "packet"
        )
        if _hash(packet_raw) != expected_hash:
            raise BlindReviewError("packet digest mismatch")
        packet_cases[packet_id] = _validate_packet(packet, packet_id, cases, sources)
        packet_answers[packet_id] = packet["answer"]
        packets_by_id[packet_id] = packet
    try:
        actual_files = set(os.listdir(directory_fd))
    except OSError as exc:
        raise BlindReviewError("packet directory cannot be listed") from exc
    expected_files = {"packet-manifest.json"} | {
        f"{packet_id}.json" for packet_id in packet_cases
    }
    if actual_files != expected_files:
        raise BlindReviewError("packet directory has an unexpected file")
    try:
        directory_after = packet_dir.lstat()
        parent_after = packet_dir.parent.lstat()
    except OSError as exc:
        raise BlindReviewError("packet directory moved during verification") from exc
    if (
        directory_after.st_dev,
        directory_after.st_ino,
        directory_after.st_mode,
        directory_after.st_mtime_ns,
        directory_after.st_ctime_ns,
    ) != directory_stamp or (
        parent_after.st_dev,
        parent_after.st_ino,
        parent_after.st_mode,
        parent_after.st_mtime_ns,
        parent_after.st_ctime_ns,
    ) != parent_stamp:
        raise BlindReviewError("packet directory changed during verification")
    return manifest, raw, packet_cases, packet_answers, packets_by_id


def _private_map(
    map_path: Path,
    manifest: dict[str, Any],
    manifest_hash: str,
    packet_cases: dict[str, str],
    packet_answers: dict[str, str],
    cases: dict[str, dict[str, Any]],
    sources: dict[str, dict[str, Any]],
    candidates: set[str],
    approved_at: datetime,
) -> tuple[dict[str, Any], bytes]:
    _absolute(map_path, "candidate map")
    try:
        metadata = map_path.lstat()
        parent = map_path.parent.lstat()
    except OSError as exc:
        raise BlindReviewError("candidate map is unavailable") from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != os.getuid()
        or stat.S_IMODE(parent.st_mode) != 0o700
    ):
        raise BlindReviewError("candidate map needs owner-only custody")
    concealed, raw = _read_json(map_path, MAX_INPUT_BYTES, "candidate map")
    _exact(
        concealed,
        {
            "schema_version",
            "cell_count",
            "packet_count",
            "packet_manifest_sha256",
            "corpus_digest",
            "source_pack_digest",
            "rubric_digest",
            "assignments",
            "dispositions",
        },
        "candidate map",
    )
    if (
        concealed.get("schema_version") != 2
        or concealed.get("cell_count") != manifest["cell_count"]
        or concealed.get("packet_count") != manifest["packet_count"]
        or concealed.get("packet_manifest_sha256") != manifest_hash
    ):
        raise BlindReviewError("candidate map does not match packet manifest")
    for field in ("corpus_digest", "source_pack_digest", "rubric_digest"):
        if concealed.get(field) != manifest[field]:
            raise BlindReviewError("candidate map input digest mismatch")
    packet_hashes = {
        item["packet_id"]: item["packet_sha256"] for item in manifest["packets"]
    }
    assignments = _array(
        concealed.get("assignments"),
        "candidate assignments",
        manifest["packet_count"],
        manifest["packet_count"],
    )
    seen_packets: set[str] = set()
    seen_runs: set[str] = set()
    seen_case_candidates: set[tuple[str, str]] = set()
    for item in assignments:
        assignment = _object(item, "candidate assignment")
        _exact(
            assignment,
            {
                "status",
                "packet_id",
                "packet_sha256",
                "case_id",
                "candidate_id",
                "run_id",
                "candidate_version",
                "model_version",
                "source_delivery",
                "answer_artifact_ref",
                "latency_ms",
                "cost_usd",
                "user_effort_minutes",
                "screening",
            },
            "candidate assignment",
        )
        if assignment.get("status") != "completed":
            raise BlindReviewError("candidate assignment is not completed")
        packet_id = _packet_id(assignment.get("packet_id"))
        if (
            packet_id not in packet_hashes
            or packet_id in seen_packets
            or assignment.get("packet_sha256") != packet_hashes[packet_id]
        ):
            raise BlindReviewError("candidate assignment packet mismatch")
        seen_packets.add(packet_id)
        case_id = _id(assignment.get("case_id"), "assignment case ID")
        candidate_id = _id(assignment.get("candidate_id"), "assignment candidate ID")
        run_id = _id(assignment.get("run_id"), "assignment run ID")
        if case_id != packet_cases[packet_id]:
            raise BlindReviewError("candidate assignment case mismatch")
        if candidate_id not in candidates:
            raise BlindReviewError("candidate assignment is outside approved rubric")
        if run_id in seen_runs or (case_id, candidate_id) in seen_case_candidates:
            raise BlindReviewError("duplicate candidate run assignment")
        seen_runs.add(run_id)
        seen_case_candidates.add((case_id, candidate_id))
        candidate_version = _text(
            assignment.get("candidate_version"), "candidate version", 256
        )
        model_version = _text(assignment.get("model_version"), "model version", 256)
        _text(assignment.get("source_delivery"), "source delivery", 256)
        _text(assignment.get("answer_artifact_ref"), "answer artifact reference", 256)
        for field in ("latency_ms", "cost_usd", "user_effort_minutes"):
            _number(assignment.get(field), field)
        screening = _object(assignment.get("screening"), "assignment screening")
        _exact(
            screening,
            {
                "custodian_id",
                "screened_at",
                "record_ref",
                "raw_answer_sha256",
                "packet_answer_sha256",
            },
            "assignment screening",
        )
        _id(screening.get("custodian_id"), "screening custodian")
        if _timestamp(screening.get("screened_at"), "screening time") < approved_at:
            raise BlindReviewError("screening preceded corpus or rubric approval")
        _text(screening.get("record_ref"), "screening reference", 256)
        _sha256(screening.get("raw_answer_sha256"), "raw answer digest")
        if _sha256(
            screening.get("packet_answer_sha256"), "packet answer digest"
        ) != _hash(packet_answers[packet_id].encode("utf-8")):
            raise BlindReviewError("screened answer does not match reviewed packet")
        _answer_is_within_view(
            "",
            packet_answers[packet_id],
            set(cases[case_id]["allowed_evidence_ids"]),
            sources,
            [
                candidate_id,
                candidate_id.replace("_", " "),
                candidate_version,
                model_version,
                *CANDIDATE_ALIASES.get(candidate_id, ()),
            ],
        )
    if seen_packets != set(packet_hashes):
        raise BlindReviewError("candidate assignments do not cover packets")
    dispositions = _array(
        concealed.get("dispositions"),
        "candidate dispositions",
        manifest["cell_count"] - manifest["packet_count"],
        manifest["cell_count"] - manifest["packet_count"],
    )
    for value in dispositions:
        disposition = _disposition_for_observation(value, cases, candidates)
        pair = (disposition["case_id"], disposition["candidate_id"])
        if pair in seen_case_candidates:
            raise BlindReviewError("duplicate candidate case disposition")
        seen_case_candidates.add(pair)
    if len(seen_case_candidates) != manifest["cell_count"]:
        raise BlindReviewError("candidate map cell count is incomplete")
    return concealed, raw


def _reviews(
    reviews_path: Path,
    manifest_hash: str,
    packet_hashes: dict[str, str],
    packet_cases: dict[str, str],
    cases: dict[str, dict[str, Any]],
) -> tuple[bytes, dict[str, list[dict[str, Any]]], dict[tuple[str, str], datetime]]:
    reviews, raw = _read_json(reviews_path, MAX_INPUT_BYTES, "blind reviews")
    _exact(
        reviews,
        {"schema_version", "packet_manifest_sha256", "reviews"},
        "blind reviews",
    )
    if (
        reviews.get("schema_version") != 1
        or reviews.get("packet_manifest_sha256") != manifest_hash
    ):
        raise BlindReviewError("blind reviews do not match packet manifest")
    items = _array(
        reviews.get("reviews"), "blind reviews", len(packet_hashes), MAX_REVIEWS
    )
    by_packet: dict[str, list[dict[str, Any]]] = {
        packet_id: [] for packet_id in packet_hashes
    }
    seen_reviewers: set[tuple[str, str]] = set()
    reviewed_at: dict[tuple[str, str], datetime] = {}
    for item in items:
        review = _object(item, "blind review")
        _exact(
            review,
            {
                "packet_id",
                "packet_sha256",
                "reviewer_id",
                "reviewed_at",
                "scores",
                "notes",
            },
            "blind review",
        )
        packet_id = _packet_id(review.get("packet_id"))
        if (
            packet_id not in packet_hashes
            or review.get("packet_sha256") != packet_hashes[packet_id]
        ):
            raise BlindReviewError("review references unknown or changed packet")
        reviewer_id = _id(review.get("reviewer_id"), "blind reviewer")
        key = (packet_id, reviewer_id)
        if key in seen_reviewers:
            raise BlindReviewError("duplicate reviewer for packet")
        seen_reviewers.add(key)
        reviewed_at[key] = _timestamp(review.get("reviewed_at"), "blind review time")
        scores = _object(review.get("scores"), "blind review scores")
        required_dimensions = set(cases[packet_cases[packet_id]]["rubric_dimensions"])
        if set(scores) != required_dimensions or set(scores) - SCORE_DIMENSIONS:
            raise BlindReviewError("blind review scores do not match case dimensions")
        for score in scores.values():
            if (
                isinstance(score, bool)
                or not isinstance(score, int)
                or not 0 <= score <= 4
            ):
                raise BlindReviewError("blind review score is out of range")
        _text(review.get("notes"), "blind review notes", 2048, allow_empty=True)
        by_packet[packet_id].append(review)
    if any(len(entries) != 1 for entries in by_packet.values()):
        raise BlindReviewError("each packet needs exactly one blind quality review")
    return raw, by_packet, reviewed_at


def _trusted_verifier_path() -> Path:
    for parent in (Path("/"), Path("/usr"), Path("/usr/bin")):
        try:
            metadata = parent.lstat()
        except OSError as exc:
            raise BlindReviewError("trusted verifier parent is unavailable") from exc
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != 0
            or metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        ):
            raise BlindReviewError("trusted verifier parent is not root controlled")
    try:
        metadata = TRUSTED_VERIFIER_PATH.lstat()
    except OSError as exc:
        raise BlindReviewError("trusted verifier is unavailable") from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        or not metadata.st_mode & stat.S_IXUSR
    ):
        raise BlindReviewError("trusted verifier is not root controlled")
    binary = _read_regular(
        TRUSTED_VERIFIER_PATH, MAX_VERIFIER_BYTES, "trusted verifier"
    )
    if _hash(binary) != TRUSTED_VERIFIER_SHA256:
        raise BlindReviewError("trusted verifier digest changed")
    return TRUSTED_VERIFIER_PATH


def _verify_detached_signature(
    *,
    payload_raw: bytes,
    signature_path: Path,
    public_key_path: Path,
    trusted_key_sha256: str,
    label: str,
) -> bytes:
    """Verify a snapshot of exact bytes with the one qualified executable."""
    verifier = _trusted_verifier_path()
    key_raw = _read_regular(public_key_path, MAX_RECEIPT_BYTES, f"{label} public key")
    if _sha256(trusted_key_sha256, f"trusted {label} key digest") != _hash(key_raw):
        raise BlindReviewError(f"{label} public key is not the pinned key")
    signature_raw = _read_regular(
        signature_path, MAX_RECEIPT_BYTES, f"{label} signature"
    )
    try:
        with tempfile.TemporaryDirectory(prefix="blind-signature-") as staging:
            key_snapshot = Path(staging) / "public.pem"
            signature_snapshot = Path(staging) / "signature.sig"
            _write_exclusive(key_snapshot, key_raw, 0o600)
            _write_exclusive(signature_snapshot, signature_raw, 0o600)
            checked = subprocess.run(
                [
                    str(verifier),
                    "dgst",
                    "-sha256",
                    "-verify",
                    str(key_snapshot),
                    "-signature",
                    str(signature_snapshot),
                ],
                input=payload_raw,
                capture_output=True,
                timeout=10,
                check=False,
                env={"PATH": os.defpath, "LANG": "C"},
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BlindReviewError(f"{label} signature could not be verified") from exc
    if checked.returncode != 0:
        raise BlindReviewError(f"{label} signature is invalid")
    return signature_raw


def _verify_control_review(
    *,
    control_review_path: Path,
    control_signature_path: Path,
    control_public_key_path: Path,
    trusted_control_key_sha256: str,
    expected_control_reviewer_id: str,
) -> tuple[dict[str, Any], bytes, bytes, datetime]:
    control, raw = _read_json(control_review_path, MAX_INPUT_BYTES, "control review")
    signature_raw = _verify_detached_signature(
        payload_raw=raw,
        signature_path=control_signature_path,
        public_key_path=control_public_key_path,
        trusted_key_sha256=trusted_control_key_sha256,
        label="control review",
    )
    _exact(
        control,
        {
            "schema_version",
            "approval",
            "packet_manifest_sha256",
            "candidate_map_sha256",
            "blind_reviews_sha256",
            "raw_observations_sha256",
            "candidate_run_digests",
            "cases",
        },
        "control review",
    )
    if control.get("schema_version") != 2:
        raise BlindReviewError("unsupported control review version")
    approval = _object(control.get("approval"), "control review approval")
    _exact(
        approval,
        {"status", "reviewer_id", "reviewed_at", "basis"},
        "control review approval",
    )
    if (
        approval.get("status") != "approved"
        or approval.get("basis")
        != "independently_retained_raw_run_control_and_disposition_evidence"
        or _id(approval.get("reviewer_id"), "control reviewer ID")
        != _id(expected_control_reviewer_id, "expected control reviewer ID")
    ):
        raise BlindReviewError("control review is not independently approved")
    reviewed_at = _timestamp(approval.get("reviewed_at"), "control review time")
    for field in (
        "packet_manifest_sha256",
        "candidate_map_sha256",
        "blind_reviews_sha256",
        "raw_observations_sha256",
    ):
        _sha256(control.get(field), f"control {field}")
    return control, raw, signature_raw, reviewed_at


def _verify_witness(
    *,
    receipt_path: Path,
    signature_path: Path,
    public_key_path: Path,
    trusted_key_sha256: str,
    expected_witness_id: str,
    trusted_control_key_sha256: str,
    expected_control_reviewer_id: str,
) -> tuple[dict[str, Any], bytes]:
    receipt_raw = _read_regular(receipt_path, MAX_RECEIPT_BYTES, "witness receipt")
    _verify_detached_signature(
        payload_raw=receipt_raw,
        signature_path=signature_path,
        public_key_path=public_key_path,
        trusted_key_sha256=trusted_key_sha256,
        label="witness",
    )
    receipt = _object(_parse_json(receipt_raw), "witness receipt")
    _exact(
        receipt,
        {
            "schema_version",
            "cell_count",
            "packet_count",
            "disposition_count",
            "packet_manifest_sha256",
            "candidate_map_sha256",
            "reviews_sha256",
            "raw_observations_sha256",
            "control_review_sha256",
            "control_signature_sha256",
            "witness_id",
            "witness_public_key_sha256",
            "control_reviewer_id",
            "control_public_key_sha256",
            "witnessed_at",
        },
        "witness receipt",
    )
    if receipt.get("schema_version") != 3:
        raise BlindReviewError("unsupported witness receipt version")
    cell_count = _count(receipt.get("cell_count"), "receipt cells", 1, MAX_CELL_COUNT)
    packet_count = _count(
        receipt.get("packet_count"), "receipt packets", 0, MAX_PACKET_COUNT
    )
    disposition_count = _count(
        receipt.get("disposition_count"), "receipt dispositions", 0, MAX_CELL_COUNT
    )
    if cell_count != packet_count + disposition_count:
        raise BlindReviewError("witness receipt cell counts differ")
    if _id(receipt.get("witness_id"), "witness ID") != _id(
        expected_witness_id, "expected witness ID"
    ):
        raise BlindReviewError("witness identity mismatch")
    if _id(receipt.get("control_reviewer_id"), "control reviewer ID") != _id(
        expected_control_reviewer_id, "expected control reviewer ID"
    ):
        raise BlindReviewError("control reviewer identity mismatch")
    if (
        trusted_key_sha256 == trusted_control_key_sha256
        or expected_witness_id == expected_control_reviewer_id
        or receipt.get("witness_public_key_sha256") != trusted_key_sha256
        or receipt.get("control_public_key_sha256") != trusted_control_key_sha256
    ):
        raise BlindReviewError("witness and control authorities are not distinct")
    _timestamp(receipt.get("witnessed_at"), "witness time")
    for field in (
        "packet_manifest_sha256",
        "candidate_map_sha256",
        "reviews_sha256",
        "raw_observations_sha256",
        "control_review_sha256",
        "control_signature_sha256",
        "witness_public_key_sha256",
        "control_public_key_sha256",
    ):
        _sha256(receipt.get(field), field)
    return receipt, receipt_raw


def _control_artifact(value: Any, label: str) -> dict[str, str]:
    item = _object(value, label)
    _exact(item, {"ref", "sha256"}, label)
    return {
        "ref": _text(item.get("ref"), f"{label} reference", 256),
        "sha256": _sha256(item.get("sha256"), f"{label} digest"),
    }


def _validate_control_case(
    value: Any,
    assignment: dict[str, Any],
    case: dict[str, Any],
    sources: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    entry = _object(value, "control case")
    if assignment["status"] != "completed":
        _exact(
            entry,
            {
                "candidate_id",
                "case_id",
                "status",
                "reason",
                "disposition_evidence",
                "control_evidence",
            },
            "noncompleted control case",
        )
        for field in ("candidate_id", "case_id", "status", "reason"):
            if entry.get(field) != assignment[field]:
                raise BlindReviewError("control disposition differs from signed map")
        disposition_evidence = _control_artifact(
            entry.get("disposition_evidence"), "control disposition evidence"
        )
        if disposition_evidence != assignment["disposition_evidence"]:
            raise BlindReviewError("control disposition evidence differs from map")
        control_evidence = _control_artifact(
            entry.get("control_evidence"), "independent disposition evidence"
        )
        if control_evidence["ref"] == disposition_evidence["ref"]:
            raise BlindReviewError("control disposition evidence is self-attested")
        return entry
    _exact(
        entry,
        {
            "status",
            "candidate_id",
            "case_id",
            "run_id",
            "observed_behavior",
            "raw_answer_sha256",
            "raw_run_artifact",
            "screening_record",
            "source_view",
            "permission_violation",
            "prompt_injection_violation",
            "permission_events",
            "prompt_payload",
        },
        "control case",
    )
    if entry.get("status") != "completed":
        raise BlindReviewError("completed control case status is invalid")
    for field in ("candidate_id", "case_id", "run_id"):
        if _id(entry.get(field), f"control {field}") != assignment[field]:
            raise BlindReviewError("control case identity differs from signed map")
    if entry.get("observed_behavior") not in ("answer", "abstained", "denied"):
        raise BlindReviewError("control case observed behavior is invalid")
    if (
        _sha256(entry.get("raw_answer_sha256"), "control raw answer digest")
        != (assignment["screening"]["raw_answer_sha256"])
    ):
        raise BlindReviewError("control raw answer differs from signed map")
    if (
        _control_artifact(entry.get("raw_run_artifact"), "raw run artifact")["ref"]
        != assignment["answer_artifact_ref"]
    ):
        raise BlindReviewError("control raw run reference differs from signed map")
    if (
        _control_artifact(entry.get("screening_record"), "screening record")["ref"]
        != assignment["screening"]["record_ref"]
    ):
        raise BlindReviewError("control screening reference differs from signed map")
    _control_artifact(entry.get("source_view"), "source view")
    if not isinstance(entry.get("permission_violation"), bool) or not isinstance(
        entry.get("prompt_injection_violation"), bool
    ):
        raise BlindReviewError("control violation flags must be Boolean")
    expected_kinds: set[str] = set()
    if case["category"] == "permission_revocation":
        expected_kinds = {
            "revocation_pre_probe",
            "revocation_acknowledgement",
            "revocation_post_probe",
        }
    else:
        if case["forbidden_evidence_ids"]:
            expected_kinds.add("forbidden_probe")
        if case["category"] == "permission_allowed":
            expected_kinds.add("allowed_probe")
    events = _array(
        entry.get("permission_events"),
        "control permission events",
        len(expected_kinds),
        len(expected_kinds),
    )
    seen_kinds: set[str] = set()
    for event_value in events:
        event = _object(event_value, "control permission event")
        _exact(event, {"kind", "observation", "event_sha256"}, "control event")
        kind = event.get("kind")
        if kind not in expected_kinds or kind in seen_kinds:
            raise BlindReviewError("control permission events do not match case")
        seen_kinds.add(kind)
        _sha256(event.get("event_sha256"), "control event digest")
        observation = _object(event.get("observation"), "control event observation")
        if kind == "revocation_acknowledgement":
            _exact(
                observation,
                {
                    "revocation_id",
                    "subject_id",
                    "target_evidence_id",
                    "status",
                    "acknowledged_at",
                    "evidence_ref",
                },
                "control revocation acknowledgement",
            )
            if observation.get("status") != "acknowledged":
                raise BlindReviewError("control revocation was not acknowledged")
            _timestamp(observation.get("acknowledged_at"), "control acknowledgement")
            _id(observation.get("revocation_id"), "control revocation ID")
        else:
            _exact(
                observation,
                {
                    "probe_id",
                    "subject_id",
                    "target_evidence_id",
                    "outcome",
                    "observed_at",
                    "evidence_ref",
                },
                "control probe",
            )
            if observation.get("outcome") not in ("allowed", "denied"):
                raise BlindReviewError("control probe outcome is invalid")
            _timestamp(observation.get("observed_at"), "control probe time")
            _id(observation.get("probe_id"), "control probe ID")
        for field in ("subject_id", "target_evidence_id", "evidence_ref"):
            _text(observation.get(field), f"control event {field}", 256)
    if seen_kinds != expected_kinds:
        raise BlindReviewError("control permission event coverage is incomplete")
    prompt_payload = entry.get("prompt_payload")
    if case["category"] == "prompt_injection":
        payload = _object(prompt_payload, "prompt payload")
        _exact(
            payload,
            {"source_evidence_id", "delivery", "answer_inspection"},
            "prompt payload",
        )
        source_id = _id(payload.get("source_evidence_id"), "prompt payload source")
        if source_id not in {
            span["evidence_id"]
            for span in case["expected_citation_spans"]
            if case["prompt_injection_sentinel"] in sources[span["evidence_id"]]["text"]
        }:
            raise BlindReviewError("prompt payload source was not preregistered")
        _control_artifact(payload.get("delivery"), "prompt payload delivery")
        _control_artifact(payload.get("answer_inspection"), "prompt answer inspection")
    elif prompt_payload is not None:
        raise BlindReviewError("control prompt payload is outside sentinel case")
    return entry


def verify_signed_bundle(
    *,
    corpus_path: Path,
    sources_path: Path,
    rubric_path: Path,
    raw_observations_path: Path,
    packet_dir: Path,
    map_path: Path,
    reviews_path: Path,
    receipt_path: Path,
    signature_path: Path,
    public_key_path: Path,
    trusted_key_sha256: str,
    expected_witness_id: str,
    control_review_path: Path,
    control_signature_path: Path,
    control_public_key_path: Path,
    trusted_control_key_sha256: str,
    expected_control_reviewer_id: str,
    packet_directory_fd: int | None = None,
    expected_packet_directory_identity: tuple[int, int] | None = None,
) -> dict[str, Any]:
    """Recheck original signed bytes without releasing candidate labels."""
    for label, path in (
        ("corpus", corpus_path),
        ("sources", sources_path),
        ("rubric", rubric_path),
        ("raw observations", raw_observations_path),
        ("packet directory", packet_dir),
        ("candidate map", map_path),
        ("blind reviews", reviews_path),
        ("witness receipt", receipt_path),
        ("witness signature", signature_path),
        ("witness public key", public_key_path),
        ("control review", control_review_path),
        ("control signature", control_signature_path),
        ("control public key", control_public_key_path),
    ):
        _absolute(path, label)
    if (
        trusted_key_sha256 == trusted_control_key_sha256
        or expected_witness_id == expected_control_reviewer_id
    ):
        raise BlindReviewError("witness and control authorities must be distinct")
    cases, sources, candidates, approved_digests, approved_at = _load_approved_inputs(
        corpus_path, sources_path, rubric_path
    )
    manifest, manifest_raw, packet_cases, packet_answers, packets_by_id = (
        _packet_manifest(
            packet_dir,
            cases,
            sources,
            approved_digests,
            packet_directory_fd=packet_directory_fd,
            expected_packet_directory_identity=expected_packet_directory_identity,
        )
    )
    manifest_hash = _hash(manifest_raw)
    concealed, map_raw = _private_map(
        map_path,
        manifest,
        manifest_hash,
        packet_cases,
        packet_answers,
        cases,
        sources,
        candidates,
        approved_at,
    )
    packet_hashes = {
        record["packet_id"]: record["packet_sha256"] for record in manifest["packets"]
    }
    reviews_raw, reviews_by_packet, reviewed_at = _reviews(
        reviews_path, manifest_hash, packet_hashes, packet_cases, cases
    )
    expected_pairs = {
        (candidate_id, case_id) for candidate_id in candidates for case_id in cases
    }
    if manifest["cell_count"] != len(expected_pairs):
        raise BlindReviewError("signed cell count differs from approved matrix")
    assignments_by_pair = {
        (assignment["candidate_id"], assignment["case_id"]): assignment
        for assignment in concealed["assignments"]
    }
    dispositions_by_pair = {
        (disposition["candidate_id"], disposition["case_id"]): disposition
        for disposition in concealed["dispositions"]
    }
    if (
        set(assignments_by_pair) & set(dispositions_by_pair)
        or set(assignments_by_pair) | set(dispositions_by_pair) != expected_pairs
    ):
        raise BlindReviewError("signed cells do not cover the complete matrix")
    observations, observations_raw = _read_json(
        raw_observations_path, MAX_INPUT_BYTES, "raw observations"
    )
    _exact(
        observations,
        {
            "schema_version",
            "cell_count",
            "corpus_digest",
            "source_pack_digest",
            "rubric_digest",
            "observations",
        },
        "raw observations",
    )
    if observations.get("schema_version") != 2:
        raise BlindReviewError("unsupported raw observation version")
    if observations.get("cell_count") != len(expected_pairs):
        raise BlindReviewError("raw observation cell count is incomplete")
    for field, digest in approved_digests.items():
        if observations.get(field) != digest:
            raise BlindReviewError("raw observations differ from approved inputs")
    raw_items = _array(
        observations.get("observations"),
        "raw observations",
        len(expected_pairs),
        len(expected_pairs),
    )
    observed_pairs: set[tuple[str, str]] = set()
    for item in raw_items:
        raw_item = _object(item, "raw observation")
        candidate_id = _id(raw_item.get("candidate_id"), "raw candidate ID")
        case_id = _id(raw_item.get("case_id"), "raw case ID")
        pair = (candidate_id, case_id)
        if pair in observed_pairs:
            raise BlindReviewError("duplicate raw candidate case cell")
        observed_pairs.add(pair)
        if raw_item.get("status") == "completed":
            if pair not in assignments_by_pair:
                raise BlindReviewError("completed raw cell lacks signed packet")
            assignment = assignments_by_pair[pair]
            if raw_item.get("run_id") != assignment["run_id"]:
                raise BlindReviewError("raw observation run differs from signed map")
            signed_packet = packets_by_id[assignment["packet_id"]]
            signed_raw_answer = _text(
                raw_item.get("raw_answer"), "signed raw answer", MAX_ANSWER
            )
            if signed_raw_answer.encode("utf-8") != signed_packet["answer"].encode(
                "utf-8"
            ):
                raise BlindReviewError("signed packet answer differs from raw answer")
            derived_packet, derived_assignment = _packet_for_observation(
                raw_item, cases, sources, candidates, approved_at
            )
            if {k: v for k, v in derived_packet.items() if k != "packet_id"} != {
                k: v for k, v in signed_packet.items() if k != "packet_id"
            } or {
                k: v
                for k, v in assignment.items()
                if k not in ("packet_id", "packet_sha256")
            } != {k: v for k, v in derived_assignment.items() if k != "packet_id"}:
                raise BlindReviewError("raw observation differs from signed packet/map")
        else:
            if pair not in dispositions_by_pair:
                raise BlindReviewError("noncompleted raw cell lacks disposition")
            derived_disposition = _disposition_for_observation(
                raw_item, cases, candidates
            )
            if derived_disposition != dispositions_by_pair[pair]:
                raise BlindReviewError("raw disposition differs from signed map")
    if observed_pairs != expected_pairs:
        raise BlindReviewError("raw observations do not match the frozen matrix")
    control, control_raw, control_signature_raw, control_reviewed_at = (
        _verify_control_review(
            control_review_path=control_review_path,
            control_signature_path=control_signature_path,
            control_public_key_path=control_public_key_path,
            trusted_control_key_sha256=trusted_control_key_sha256,
            expected_control_reviewer_id=expected_control_reviewer_id,
        )
    )
    if (
        control["packet_manifest_sha256"] != manifest_hash
        or control["candidate_map_sha256"] != _hash(map_raw)
        or control["blind_reviews_sha256"] != _hash(reviews_raw)
        or control["raw_observations_sha256"] != _hash(observations_raw)
    ):
        raise BlindReviewError("control review did not bind current artifact bytes")
    run_digests = _object(
        control.get("candidate_run_digests"), "control candidate run digests"
    )
    if set(run_digests) != candidates:
        raise BlindReviewError("control review candidate set is incomplete")
    for value in run_digests.values():
        _sha256(value, "control candidate run digest")
    control_entries = _array(
        control.get("cases"), "control cases", len(expected_pairs), len(expected_pairs)
    )
    control_by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    for value in control_entries:
        entry = _object(value, "control case")
        pair = (
            _id(entry.get("candidate_id"), "control candidate ID"),
            _id(entry.get("case_id"), "control case ID"),
        )
        if pair not in expected_pairs or pair in control_by_pair:
            raise BlindReviewError("control case is duplicate or outside matrix")
        signed_cell = assignments_by_pair.get(pair, dispositions_by_pair.get(pair))
        if signed_cell is None:
            raise BlindReviewError("control case is outside signed cells")
        control_by_pair[pair] = _validate_control_case(
            entry, signed_cell, cases[pair[1]], sources
        )
    if set(control_by_pair) != expected_pairs:
        raise BlindReviewError("control case coverage is incomplete")
    receipt, receipt_raw = _verify_witness(
        receipt_path=receipt_path,
        signature_path=signature_path,
        public_key_path=public_key_path,
        trusted_key_sha256=trusted_key_sha256,
        expected_witness_id=expected_witness_id,
        trusted_control_key_sha256=trusted_control_key_sha256,
        expected_control_reviewer_id=expected_control_reviewer_id,
    )
    if (
        receipt["packet_manifest_sha256"] != manifest_hash
        or receipt["cell_count"] != manifest["cell_count"]
        or receipt["packet_count"] != manifest["packet_count"]
        or receipt["disposition_count"] != len(concealed["dispositions"])
        or receipt["candidate_map_sha256"] != _hash(map_raw)
        or receipt["reviews_sha256"] != _hash(reviews_raw)
        or receipt["raw_observations_sha256"] != _hash(observations_raw)
        or receipt["control_review_sha256"] != _hash(control_raw)
        or receipt["control_signature_sha256"] != _hash(control_signature_raw)
    ):
        raise BlindReviewError("witness did not sign the current artifact hashes")
    witnessed_at = _timestamp(receipt["witnessed_at"], "witness time")
    if not approved_at <= control_reviewed_at <= witnessed_at:
        raise BlindReviewError("control review and witness times are out of order")
    quality_reviewers: set[str] = set()
    screening_custodians: set[str] = set()
    for assignment in concealed["assignments"]:
        packet_id = assignment["packet_id"]
        screening_at = _timestamp(
            assignment["screening"]["screened_at"], "screening time"
        )
        screening_custodians.add(assignment["screening"]["custodian_id"])
        for review in reviews_by_packet[packet_id]:
            review_at = reviewed_at[(packet_id, review["reviewer_id"])]
            quality_reviewers.add(review["reviewer_id"])
            if not screening_at <= review_at <= control_reviewed_at:
                raise BlindReviewError(
                    "screening, quality, and control review times are out of order"
                )
    if (
        expected_control_reviewer_id in quality_reviewers | screening_custodians
        or expected_witness_id in quality_reviewers | screening_custodians
    ):
        raise BlindReviewError("review or witness roles overlap")
    assignments = [
        {**assignment, "blind_reviews": reviews_by_packet[assignment["packet_id"]]}
        for assignment in concealed["assignments"]
    ]
    output = {
        "schema_version": 3,
        "cell_count": manifest["cell_count"],
        "packet_count": manifest["packet_count"],
        "disposition_count": len(concealed["dispositions"]),
        "packet_manifest_sha256": manifest_hash,
        "candidate_map_sha256": _hash(map_raw),
        "reviews_sha256": _hash(reviews_raw),
        "control_review_sha256": _hash(control_raw),
        "control_signature_sha256": _hash(control_signature_raw),
        "raw_observations_sha256": _hash(observations_raw),
        "witness_receipt_sha256": _hash(receipt_raw),
        "witness_id": receipt["witness_id"],
        "control_reviewer_id": expected_control_reviewer_id,
        "witnessed_at": receipt["witnessed_at"],
        "assignments": assignments,
        "dispositions": concealed["dispositions"],
    }
    return {
        "assembly": output,
        "manifest": manifest,
        "packets_by_id": packets_by_id,
        "concealed_map": concealed,
        "reviews_by_packet": reviews_by_packet,
        "control_review": control,
        "raw_observations": observations,
        "cases": cases,
        "sources": sources,
        "candidates": candidates,
        "approved_digests": approved_digests,
        "approved_at": approved_at,
    }


def _assert_unblind_private_parent(target: _OutputTarget, map_path: Path) -> None:
    _require_private_directory_fd(target.directory_fd)
    try:
        metadata = map_path.parent.lstat()
        resolved = map_path.parent.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise BlindReviewError("private map parent is unavailable") from exc
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or (metadata.st_dev, metadata.st_ino)
        != _directory_identity(target.directory_fd)
        or resolved != target.route.resolved_parent
    ):
        raise BlindReviewError("unblinded output must remain with the private map")


def verify_and_unblind(
    *,
    corpus_path: Path,
    sources_path: Path,
    rubric_path: Path,
    raw_observations_path: Path,
    packet_dir: Path,
    map_path: Path,
    reviews_path: Path,
    receipt_path: Path,
    signature_path: Path,
    public_key_path: Path,
    trusted_key_sha256: str,
    expected_witness_id: str,
    control_review_path: Path,
    control_signature_path: Path,
    control_public_key_path: Path,
    trusted_control_key_sha256: str,
    expected_control_reviewer_id: str,
    output_path: Path,
) -> dict[str, Any]:
    """Release labels only after the complete v3 signed freeze is verified."""
    _absolute(output_path, "unblinded output")
    consumed = [
        corpus_path,
        sources_path,
        rubric_path,
        raw_observations_path,
        map_path,
        reviews_path,
        receipt_path,
        signature_path,
        public_key_path,
        control_review_path,
        control_signature_path,
        control_public_key_path,
    ]
    target: _OutputTarget | None = None
    published_file: _CreatedFile | None = None
    released = False
    try:
        target = _open_output_target(
            output_path, consumed, [packet_dir.resolve(strict=True)]
        )
        _assert_unblind_private_parent(target, map_path)
        verified = verify_signed_bundle(
            corpus_path=corpus_path,
            sources_path=sources_path,
            rubric_path=rubric_path,
            raw_observations_path=raw_observations_path,
            packet_dir=packet_dir,
            map_path=map_path,
            reviews_path=reviews_path,
            receipt_path=receipt_path,
            signature_path=signature_path,
            public_key_path=public_key_path,
            trusted_key_sha256=trusted_key_sha256,
            expected_witness_id=expected_witness_id,
            control_review_path=control_review_path,
            control_signature_path=control_signature_path,
            control_public_key_path=control_public_key_path,
            trusted_control_key_sha256=trusted_control_key_sha256,
            expected_control_reviewer_id=expected_control_reviewer_id,
            packet_directory_fd=target.packet_directory_fds[0],
            expected_packet_directory_identity=_directory_identity(
                target.packet_directory_fds[0]
            ),
        )
        _assert_output_target(target)
        _assert_unblind_private_parent(target, map_path)
        output = verified["assembly"]
        raw = _encoded_file(output)
        if len(raw) > MAX_INPUT_BYTES:
            raise BlindReviewError("unblinded assignment exceeds its byte bound")
        published_file = _write_new_output(target, raw)
        _assert_output_target(target, parent_was_written=True, require_fresh=False)
        _assert_unblind_private_parent(target, map_path)
        metadata = os.stat(
            output_path.name, dir_fd=target.directory_fd, follow_symlinks=False
        )
        if (
            not stat.S_ISREG(metadata.st_mode)
            or (metadata.st_dev, metadata.st_ino) != published_file.identity
        ):
            raise BlindReviewError("unblinded output identity changed")
        released = True
        return output
    except (EvaluationError, OSError) as exc:
        raise BlindReviewError("unblinded output could not be published") from exc
    finally:
        if target is not None:
            if published_file is not None:
                try:
                    if not released:
                        _unlink_if_same_file(
                            target.directory_fd,
                            output_path.name,
                            published_file.identity,
                        )
                finally:
                    published_file.close()
            _close_output_target(target)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Synthetic blind review packet custody"
    )
    actions = parser.add_subparsers(dest="action", required=True)
    prepare = actions.add_parser(
        "prepare", help="create anonymous packets and private map"
    )
    prepare.add_argument("--corpus", required=True, type=Path)
    prepare.add_argument("--sources", required=True, type=Path)
    prepare.add_argument("--rubric", required=True, type=Path)
    prepare.add_argument("--observations", required=True, type=Path)
    prepare.add_argument("--packet-dir", required=True, type=Path)
    prepare.add_argument("--map", required=True, type=Path)
    unblind = actions.add_parser(
        "unblind", help="verify signed freeze before label reveal"
    )
    unblind.add_argument("--corpus", required=True, type=Path)
    unblind.add_argument("--sources", required=True, type=Path)
    unblind.add_argument("--rubric", required=True, type=Path)
    unblind.add_argument("--raw-observations", required=True, type=Path)
    unblind.add_argument("--packet-dir", required=True, type=Path)
    unblind.add_argument("--map", required=True, type=Path)
    unblind.add_argument("--reviews", required=True, type=Path)
    unblind.add_argument("--receipt", required=True, type=Path)
    unblind.add_argument("--signature", required=True, type=Path)
    unblind.add_argument("--public-key", required=True, type=Path)
    unblind.add_argument("--trusted-key-sha256", required=True)
    unblind.add_argument("--expected-witness-id", required=True)
    unblind.add_argument("--control-review", required=True, type=Path)
    unblind.add_argument("--control-signature", required=True, type=Path)
    unblind.add_argument("--control-public-key", required=True, type=Path)
    unblind.add_argument("--trusted-control-key-sha256", required=True)
    unblind.add_argument("--expected-control-reviewer-id", required=True)
    unblind.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.action == "prepare":
            result = prepare_packets(
                corpus_path=args.corpus,
                sources_path=args.sources,
                rubric_path=args.rubric,
                observations_path=args.observations,
                packet_dir=args.packet_dir,
                map_path=args.map,
            )
            print(
                json.dumps(
                    {
                        "packet_count": result["packet_count"],
                        "packet_manifest_sha256": _hash(
                            _read_regular(
                                args.packet_dir / "packet-manifest.json",
                                MAX_INPUT_BYTES,
                                "packet manifest",
                            )
                        ),
                    },
                    sort_keys=True,
                )
            )
        else:
            result = verify_and_unblind(
                corpus_path=args.corpus,
                sources_path=args.sources,
                rubric_path=args.rubric,
                raw_observations_path=args.raw_observations,
                packet_dir=args.packet_dir,
                map_path=args.map,
                reviews_path=args.reviews,
                receipt_path=args.receipt,
                signature_path=args.signature,
                public_key_path=args.public_key,
                trusted_key_sha256=args.trusted_key_sha256,
                expected_witness_id=args.expected_witness_id,
                control_review_path=args.control_review,
                control_signature_path=args.control_signature,
                control_public_key_path=args.control_public_key,
                trusted_control_key_sha256=args.trusted_control_key_sha256,
                expected_control_reviewer_id=args.expected_control_reviewer_id,
                output_path=args.output,
            )
            print(
                json.dumps(
                    {
                        "verified_packet_count": result["packet_count"],
                        "witness_receipt_sha256": result["witness_receipt_sha256"],
                    },
                    sort_keys=True,
                )
            )
    except (BlindReviewError, OSError, UnicodeError, ValueError):
        print("blind review operation rejected", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
