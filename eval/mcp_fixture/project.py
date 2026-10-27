"""Project the draft evaluator pack to one synthetic, read-only MCP case.

Only this offline command reads the evaluator corpus and full source pack. The
stdio server reads the output projection and cannot choose another case.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from . import server as mcp

EVAL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = EVAL_ROOT / "corpus/v1/cases.json"
DEFAULT_SOURCES = EVAL_ROOT / "corpus/v1/sources.json"
MAX_INPUT_BYTES = 256 * 1024
MAX_PACK_SOURCES = 64
SOURCE_KEYS = {"evidence_id", "data_class", "origin", "text"}
PUBLIC_CLASSES = {"synthetic", "public"}


class ProjectionError(ValueError):
    """A projection would expose an unapproved or ambiguous source view."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _read_json_and_raw(path: Path) -> tuple[Any, bytes]:
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            raise ProjectionError("input file exceeds the fixture bound")
        return mcp.parse_json_bytes(raw), raw
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        RecursionError,
    ) as exc:
        raise ProjectionError("input file is not readable UTF-8 JSON") from exc


def _read_json(path: Path) -> Any:
    return _read_json_and_raw(path)[0]


def _object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProjectionError(f"{name} must be an object")
    return value


def _text(value: Any, name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ProjectionError(f"{name} must be nonempty bounded text")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ProjectionError(f"{name} has invalid Unicode") from exc
    return value


def _source_ids(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or len(value) > mcp.MAX_CASE_SOURCES:
        raise ProjectionError(f"{name} must be a bounded array")
    ids = [_text(item, name, mcp.MAX_SOURCE_ID) for item in value]
    if any(mcp.SOURCE_ID_PATTERN.fullmatch(source_id) is None for source_id in ids):
        raise ProjectionError(f"{name} has an invalid source ID")
    if len(ids) != len(set(ids)):
        raise ProjectionError(f"{name} has duplicate IDs")
    return ids


def _source_index(pack: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if (
        pack.get("schema_version") != 1
        or pack.get("source_pack_id") != "synthetic-research-pack-v1"
    ):
        raise ProjectionError("unsupported source pack")
    if set(pack) != {"schema_version", "source_pack_id", "description", "sources"}:
        raise ProjectionError("source pack has unreviewed fields")
    sources = pack.get("sources")
    if not isinstance(sources, list) or not 1 <= len(sources) <= MAX_PACK_SOURCES:
        raise ProjectionError("source pack size is outside the fixture bound")
    indexed: dict[str, dict[str, Any]] = {}
    for source_value in sources:
        source = _object(source_value, "source")
        if set(source) != SOURCE_KEYS:
            raise ProjectionError("source record has unreviewed fields")
        evidence_id = _text(source.get("evidence_id"), "evidence ID", mcp.MAX_SOURCE_ID)
        if mcp.SOURCE_ID_PATTERN.fullmatch(evidence_id) is None:
            raise ProjectionError("source pack has an invalid evidence ID")
        origin = _text(source.get("origin"), "source origin", mcp.MAX_SOURCE_ORIGIN)
        _text(source.get("text"), "source text", mcp.MAX_SOURCE_TEXT)
        if source.get("data_class") not in PUBLIC_CLASSES:
            raise ProjectionError("source class is outside synthetic/public scope")
        if len(f"{origin} / {evidence_id}") > mcp.MAX_SOURCE_TITLE:
            raise ProjectionError("source title exceeds the fixture bound")
        if evidence_id in indexed:
            raise ProjectionError("source pack has duplicate evidence IDs")
        indexed[evidence_id] = source
    return indexed


def _build_projection(
    case_id: str,
    corpus: dict[str, Any],
    pack: dict[str, Any],
    distribution_status: str,
) -> tuple[dict[str, Any], str, set[str]]:
    """Build one case from the already parsed, single-read input snapshots."""
    if mcp.CASE_ID_PATTERN.fullmatch(case_id) is None:
        raise ProjectionError("case ID is invalid")
    source_by_id = _source_index(pack)
    if (
        corpus.get("schema_version") != 1
        or corpus.get("corpus_id") != "synthetic-matched-research-v1"
    ):
        raise ProjectionError("unsupported corpus")
    if corpus.get("source_pack_id") != pack["source_pack_id"]:
        raise ProjectionError("corpus source pack ID mismatch")
    source_pack_digest = _digest(pack)
    if corpus.get("source_pack_digest") != source_pack_digest:
        raise ProjectionError("corpus source pack digest mismatch")
    cases = corpus.get("cases")
    if not isinstance(cases, list) or len(cases) != 24:
        raise ProjectionError("draft v1 corpus must contain exactly 24 cases")

    selected: dict[str, Any] | None = None
    seen_case_ids: set[str] = set()
    for case_value in cases:
        case = _object(case_value, "case")
        current_id = _text(case.get("case_id"), "case ID", 7)
        if (
            mcp.CASE_ID_PATTERN.fullmatch(current_id) is None
            or current_id in seen_case_ids
        ):
            raise ProjectionError("case IDs must be unique draft v1 IDs")
        seen_case_ids.add(current_id)
        case_question = _text(case.get("question"), "case question", 1000)
        if any(ord(character) < 32 for character in case_question):
            raise ProjectionError("case question must be one printable line")
        if case.get("data_class") not in PUBLIC_CLASSES:
            raise ProjectionError("case class is outside synthetic/public scope")
        allowed = _source_ids(case.get("allowed_evidence_ids"), "allowed evidence IDs")
        forbidden = _source_ids(
            case.get("forbidden_evidence_ids"), "forbidden evidence IDs"
        )
        if not allowed or set(allowed) & set(forbidden):
            raise ProjectionError("case source policy is empty or overlapping")
        if not set(allowed + forbidden) <= set(source_by_id):
            raise ProjectionError("case refers to an unknown source ID")
        if current_id == case_id:
            selected = case
    if selected is None:
        raise ProjectionError("case ID is not in the draft v1 corpus")
    question = selected["question"]

    projected_sources: list[dict[str, Any]] = []
    for evidence_id in sorted(selected["allowed_evidence_ids"]):
        source = source_by_id[evidence_id]
        projected_sources.append(
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

    return (
        {
            "schema_version": 2,
            "distribution_status": distribution_status,
            "case_id": case_id,
            "source_pack_id": pack["source_pack_id"],
            "source_pack_digest": source_pack_digest,
            "corpus_digest": _digest(corpus),
            "citation_link_parity": "unproved",
            "sources": projected_sources,
        },
        question,
        seen_case_ids,
    )


def build_projection(
    case_id: str, cases_path: Path, sources_path: Path
) -> dict[str, Any]:
    """Produce a visibly non-distributable local projection for one draft case."""
    pack = _object(_read_json(sources_path), "source pack")
    corpus = _object(_read_json(cases_path), "corpus")
    projection, _, _ = _build_projection(case_id, corpus, pack, mcp.DRAFT_STATUS)
    return projection


def _approved_status(value: dict[str, Any], name: str) -> None:
    approval = value.get("approval")
    if not isinstance(approval, dict) or approval.get("status") != "approved":
        raise ProjectionError(f"{name} approval is pending")
    _text(approval.get("reviewer_id"), f"{name} reviewer", 200)
    _text(approval.get("reviewed_at"), f"{name} approval time", 40)


def _matches_bytes(raw: bytes, expected_sha256: str, name: str) -> None:
    if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), expected_sha256):
        raise ProjectionError(f"{name} bytes differ from approved manifest")


def build_manifest_candidate(
    cases_path: Path, sources_path: Path, rubric_path: Path
) -> dict[str, Any]:
    """Calculate non-authorizing pins for independent review and registration."""
    corpus_value, corpus_raw = _read_json_and_raw(cases_path)
    pack_value, pack_raw = _read_json_and_raw(sources_path)
    rubric_value, rubric_raw = _read_json_and_raw(rubric_path)
    corpus = _object(corpus_value, "corpus")
    pack = _object(pack_value, "source pack")
    rubric = _object(rubric_value, "rubric")
    _approved_status(corpus, "corpus")
    _approved_status(rubric, "rubric")
    if (
        rubric.get("schema_version") != 1
        or rubric.get("rubric_id") != "synthetic-matched-rubric-v1"
    ):
        raise ProjectionError("approved rubric identity is unsupported")
    expected_ids = [f"case-{number:02d}" for number in range(1, 25)]
    cases = []
    for case_id in expected_ids:
        projection, question, case_ids = _build_projection(
            case_id, corpus, pack, mcp.APPROVED_STATUS
        )
        if case_ids != set(expected_ids):
            raise ProjectionError(
                "approved corpus case set is not case-01 through case-24"
            )
        projection_bytes = _canonical_json(projection) + b"\n"
        mcp.validate_projection_bytes(projection_bytes, case_id)
        cases.append(
            {
                "case_id": case_id,
                "question_sha256": hashlib.sha256(
                    question.encode("utf-8") + b"\n"
                ).hexdigest(),
                "projection_sha256": hashlib.sha256(projection_bytes).hexdigest(),
            }
        )
    return {
        "schema_version": 1,
        "approval": {"status": "pending"},
        "data_use_destination": "chatgpt_enterprise",
        "corpus_sha256": hashlib.sha256(corpus_raw).hexdigest(),
        "sources_sha256": hashlib.sha256(pack_raw).hexdigest(),
        "rubric_sha256": hashlib.sha256(rubric_raw).hexdigest(),
        "cases": cases,
    }


def _write_new_files(outputs: list[tuple[Path, bytes]]) -> None:
    if len({str(path.absolute()) for path, _ in outputs}) != len(outputs):
        raise ProjectionError("output paths must be different")
    if any(path.exists() or path.is_symlink() for path, _ in outputs):
        raise ProjectionError("output file already exists")
    created: list[Path] = []
    try:
        for path, data in outputs:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            created.append(path)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
    except OSError as exc:
        for path in created:
            path.unlink(missing_ok=True)
        raise ProjectionError(
            "output file already exists or cannot be written"
        ) from exc


def _publish_packet_dir(
    packet_dir: Path,
    question_data: bytes,
    projection_data: bytes,
    question_sha256: str,
    projection_sha256: str,
) -> None:
    """Publish a complete, pinned packet with one same-parent directory rename.

    The sibling staging directory is private. The destination remains absent
    throughout file creation and verification, including an interrupted write.
    """
    if packet_dir.exists() or packet_dir.is_symlink():
        raise ProjectionError("packet directory already exists")
    if not packet_dir.parent.is_dir():
        raise ProjectionError("packet parent directory does not exist")
    try:
        stage = Path(
            tempfile.mkdtemp(prefix=".mcp-packet-staging-", dir=packet_dir.parent)
        )
    except OSError as exc:
        raise ProjectionError(
            "private packet staging directory cannot be created"
        ) from exc
    try:
        for filename, data, expected_sha256 in (
            ("question.txt", question_data, question_sha256),
            ("projection.json", projection_data, projection_sha256),
        ):
            staged_file = stage / filename
            descriptor = os.open(
                staged_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            )
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            staged_data = staged_file.read_bytes()
            if not hmac.compare_digest(staged_data, data):
                raise ProjectionError("staged packet bytes differ from approved bytes")
            _matches_bytes(staged_data, expected_sha256, filename)
        if packet_dir.exists() or packet_dir.is_symlink():
            raise ProjectionError("packet directory already exists")
        os.rename(stage, packet_dir)
    except OSError as exc:
        raise ProjectionError("packet could not be written or published") from exc
    finally:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-id", help="one v1 corpus case, for example case-17")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES)
    parser.add_argument("--output", type=Path, help="new draft projection JSON file")
    parser.add_argument(
        "--packet-dir", type=Path, help="new approved tester packet directory"
    )
    parser.add_argument("--prepare-manifest-candidate", type=Path)
    parser.add_argument("--draft-local", action="store_true")
    parser.add_argument("--rubric", type=Path)
    parser.add_argument("--approval-manifest", type=Path)
    parser.add_argument("--approved-manifest-sha256")
    args = parser.parse_args(argv)
    try:
        if args.prepare_manifest_candidate is not None:
            if (
                args.case_id is not None
                or args.output is not None
                or args.packet_dir is not None
                or args.approval_manifest is not None
                or args.approved_manifest_sha256 is not None
                or args.draft_local
                or args.rubric is None
            ):
                raise ProjectionError(
                    "manifest preparation requires only approved corpus/source/rubric inputs and a new candidate output"
                )
            candidate = build_manifest_candidate(args.cases, args.sources, args.rubric)
            candidate_bytes = _canonical_json(candidate) + b"\n"
            if len(candidate_bytes) > mcp.MAX_APPROVAL_MANIFEST_BYTES:
                raise ProjectionError("candidate manifest exceeds the fixture bound")
            _write_new_files([(args.prepare_manifest_candidate, candidate_bytes)])
            print(
                json.dumps(
                    {
                        "approval_status": "PENDING_NON_AUTHORIZING",
                        "candidate_sha256": hashlib.sha256(candidate_bytes).hexdigest(),
                        "case_count": len(candidate["cases"]),
                    },
                    sort_keys=True,
                )
            )
            return 0
        if args.case_id is None:
            raise ProjectionError("one-case projection requires --case-id")
        if args.draft_local:
            if args.output is None or args.packet_dir is not None:
                raise ProjectionError(
                    "draft-local requires --output and no --packet-dir"
                )
            if any(
                value is not None
                for value in (
                    args.rubric,
                    args.approval_manifest,
                    args.approved_manifest_sha256,
                )
            ):
                raise ProjectionError(
                    "draft-local mode cannot create a tester question"
                )
            projection = build_projection(args.case_id, args.cases, args.sources)
            question_data = None
        else:
            if (
                args.output is not None
                or args.packet_dir is None
                or args.rubric is None
                or args.approval_manifest is None
                or args.approved_manifest_sha256 is None
            ):
                raise ProjectionError(
                    "distribution requires a fresh --packet-dir, rubric, and independently registered approval manifest"
                )
            manifest = mcp.load_approval_manifest(
                args.approval_manifest, args.approved_manifest_sha256
            )
            corpus_value, corpus_raw = _read_json_and_raw(args.cases)
            pack_value, pack_raw = _read_json_and_raw(args.sources)
            rubric_value, rubric_raw = _read_json_and_raw(args.rubric)
            corpus = _object(corpus_value, "corpus")
            pack = _object(pack_value, "source pack")
            rubric = _object(rubric_value, "rubric")
            _matches_bytes(corpus_raw, manifest.corpus_sha256, "corpus")
            _matches_bytes(pack_raw, manifest.sources_sha256, "source pack")
            _matches_bytes(rubric_raw, manifest.rubric_sha256, "rubric")
            _approved_status(corpus, "corpus")
            _approved_status(rubric, "rubric")
            if (
                rubric.get("schema_version") != 1
                or rubric.get("rubric_id") != "synthetic-matched-rubric-v1"
            ):
                raise ProjectionError("approved rubric identity is unsupported")
            projection, question, case_ids = _build_projection(
                args.case_id, corpus, pack, mcp.APPROVED_STATUS
            )
            if case_ids != set(manifest.cases):
                raise ProjectionError("approved manifest case set differs from corpus")
            question_data = question.encode("utf-8") + b"\n"
        data = _canonical_json(projection) + b"\n"
        mcp.validate_projection_bytes(data, args.case_id)
        if question_data is not None:
            assert args.packet_dir is not None
            case_pin = manifest.cases[args.case_id]
            _matches_bytes(question_data, case_pin.question_sha256, "question")
            _matches_bytes(data, case_pin.projection_sha256, "projection")
            _publish_packet_dir(
                args.packet_dir,
                question_data,
                data,
                case_pin.question_sha256,
                case_pin.projection_sha256,
            )
        else:
            assert args.output is not None
            _write_new_files([(args.output, data)])
    except (ProjectionError, mcp.FixtureError, TypeError, ValueError) as exc:
        print(f"projection refused: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "case_id": projection["case_id"],
                "source_pack_digest": projection["source_pack_digest"],
                "projection_sha256": hashlib.sha256(data).hexdigest(),
                "source_count": len(projection["sources"]),
                "citation_link_parity": "unproved",
                "distribution_status": projection["distribution_status"],
                "approval_manifest_sha256": (
                    args.approved_manifest_sha256 if not args.draft_local else None
                ),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
