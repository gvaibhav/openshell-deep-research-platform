"""Reviewer-only citation targets for one preverified matched-evaluation packet.

CR-0021 / DR-FEAS-004. The caller supplies independently registered SHA-256
pins for exact approved corpus/source bytes and values from a separately
verified pre-distribution control attestation over the manifest and packet.
It must read packet bytes from the held packet-directory FD. This module
checks supplied values; it does not verify signatures, establish human
approval, or distribute a projection. The current v2 path does not meet
the attestation precondition.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any

MAX_INPUT_BYTES = 1024 * 1024
MAX_PACKET_BYTES = 128 * 1024
MAX_PROJECTION_BYTES = 128 * 1024
MAX_TARGETS = 128
MAX_SOURCES = 64
MAX_ALLOWED_SOURCES = 16
MAX_SOURCE_TEXT = 4096
MAX_CITATIONS = 32
ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
PACKET_ID_RE = re.compile(r"bp-[0-9a-f]{32}\Z")
DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
TIME_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})\Z"
)


class TargetProjectionError(ValueError):
    """The inputs cannot support a reviewer-only target projection."""


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise TargetProjectionError("invalid JSON value") from exc


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise TargetProjectionError("duplicate JSON key")
        result[key] = value
    return result


def _reject_nonfinite(_: str) -> Any:
    raise TargetProjectionError("nonfinite JSON number")


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TargetProjectionError(f"{label} must be an object")
    return value


def _read_object(raw: bytes, label: str, limit: int) -> dict[str, Any]:
    if not isinstance(raw, bytes) or len(raw) > limit:
        raise TargetProjectionError(f"{label} exceeds its byte bound")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_keys,
            parse_constant=_reject_nonfinite,
        )
        _canonical(value)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise TargetProjectionError(f"{label} is not valid UTF-8 JSON") from exc
    return _object(value, label)


def _exact(value: dict[str, Any], keys: set[str], label: str) -> None:
    if set(value) != keys:
        raise TargetProjectionError(f"{label} has missing or unsupported fields")


def _array(value: Any, label: str, minimum: int, maximum: int) -> list[Any]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise TargetProjectionError(f"{label} has an invalid array size")
    return value


def _text(value: Any, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise TargetProjectionError(f"{label} must be bounded nonempty text")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise TargetProjectionError(f"{label} contains invalid Unicode") from exc
    return value


def _id(value: Any, label: str) -> str:
    result = _text(value, label, 128)
    if ID_RE.fullmatch(result) is None:
        raise TargetProjectionError(f"{label} has invalid syntax")
    return result


def _digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or DIGEST_RE.fullmatch(value) is None:
        raise TargetProjectionError(f"{label} is not SHA-256")
    return value


def _ids(value: Any, label: str, minimum: int, maximum: int) -> list[str]:
    result = [_id(item, label) for item in _array(value, label, minimum, maximum)]
    if len(result) != len(set(result)):
        raise TargetProjectionError(f"{label} has duplicate IDs")
    return result


def _approved(value: Any) -> None:
    approval = _object(value, "corpus approval")
    _exact(approval, {"status", "reviewer_id", "reviewed_at"}, "corpus approval")
    if approval.get("status") != "approved":
        raise TargetProjectionError("corpus is not approved")
    _id(approval.get("reviewer_id"), "corpus reviewer")
    stamped = _text(approval.get("reviewed_at"), "corpus approval time", 40)
    if TIME_RE.fullmatch(stamped) is None:
        raise TargetProjectionError("corpus approval time needs an offset")
    try:
        moment = datetime.fromisoformat(stamped)
    except ValueError as exc:
        raise TargetProjectionError("corpus approval time is invalid") from exc
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise TargetProjectionError("corpus approval time needs an offset")


def _source_index(pack: dict[str, Any]) -> dict[str, dict[str, str]]:
    _exact(
        pack,
        {"schema_version", "source_pack_id", "description", "sources"},
        "source pack",
    )
    if type(pack["schema_version"]) is not int or pack["schema_version"] != 1:
        raise TargetProjectionError("unsupported source-pack version")
    _id(pack["source_pack_id"], "source-pack ID")
    _text(pack["description"], "source-pack description", MAX_INPUT_BYTES)
    sources: dict[str, dict[str, str]] = {}
    for value in _array(pack["sources"], "source pack", 1, MAX_SOURCES):
        source = _object(value, "source")
        _exact(source, {"evidence_id", "data_class", "origin", "text"}, "source")
        source_id = _id(source["evidence_id"], "source ID")
        if source_id in sources:
            raise TargetProjectionError("duplicate source ID")
        if source["data_class"] not in ("public", "synthetic"):
            raise TargetProjectionError("source class is not public or synthetic")
        sources[source_id] = {
            "evidence_id": source_id,
            "origin": _text(source["origin"], "source origin", 256),
            "text": _text(source["text"], "source text", MAX_SOURCE_TEXT),
        }
    return sources


def _case_index(
    corpus: dict[str, Any], sources: dict[str, dict[str, str]]
) -> dict[str, dict[str, Any]]:
    _exact(
        corpus,
        {
            "schema_version",
            "corpus_id",
            "source_pack_id",
            "source_pack_digest",
            "permission_profile_id",
            "description",
            "approval",
            "cases",
        },
        "corpus",
    )
    if type(corpus["schema_version"]) is not int or corpus["schema_version"] != 1:
        raise TargetProjectionError("unsupported corpus version")
    _id(corpus["corpus_id"], "corpus ID")
    _id(corpus["permission_profile_id"], "permission profile ID")
    _text(corpus["description"], "corpus description", MAX_INPUT_BYTES)
    _approved(corpus["approval"])
    cases: dict[str, dict[str, Any]] = {}
    for value in _array(corpus["cases"], "corpus cases", 20, 30):
        case = _object(value, "case")
        case_id = _id(case.get("case_id"), "case ID")
        if case_id in cases:
            raise TargetProjectionError("duplicate case ID")
        if case.get("data_class") not in ("public", "synthetic"):
            raise TargetProjectionError("case class is not public or synthetic")
        _text(case.get("question"), "case question", 4096)
        allowed = _ids(
            case.get("allowed_evidence_ids"), "allowed source", 1, MAX_ALLOWED_SOURCES
        )
        forbidden = _ids(
            case.get("forbidden_evidence_ids"), "forbidden source", 0, MAX_SOURCES
        )
        if not set(allowed).isdisjoint(forbidden):
            raise TargetProjectionError("allowed and forbidden sources overlap")
        if any(source_id not in sources for source_id in allowed + forbidden):
            raise TargetProjectionError("case references missing source")
        cases[case_id] = case
    return cases


def _targets(case: dict[str, Any], visible: dict[str, str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for index, value in enumerate(
        _array(case.get("expected_citation_spans"), "citation targets", 0, MAX_TARGETS)
    ):
        anchor = _object(value, "citation target")
        _exact(anchor, {"evidence_id", "quote"}, "citation target")
        source_id = _id(anchor["evidence_id"], "target source ID")
        quote = _text(anchor["quote"], "target anchor quote", MAX_SOURCE_TEXT)
        if source_id not in visible or quote not in visible[source_id]:
            raise TargetProjectionError(
                "target is not an exact span of a visible source"
            )
        key = (source_id, quote)
        if key in seen:
            raise TargetProjectionError("duplicate citation target")
        seen.add(key)
        result.append(
            {"target_index": index, "evidence_id": source_id, "anchor_quote": quote}
        )
    return result


def _validate_packet(
    packet: dict[str, Any],
    case: dict[str, Any],
    sources: dict[str, dict[str, str]],
    preverified_packet_id: str,
) -> None:
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
    if type(packet["schema_version"]) is not int or packet["schema_version"] != 1:
        raise TargetProjectionError("unsupported packet version")
    if (
        not isinstance(preverified_packet_id, str)
        or PACKET_ID_RE.fullmatch(preverified_packet_id) is None
        or packet["packet_id"] != preverified_packet_id
    ):
        raise TargetProjectionError("packet ID differs from signed manifest")
    if packet["case_id"] != case["case_id"] or packet["question"] != case["question"]:
        raise TargetProjectionError(
            "packet case or question differs from approved corpus"
        )
    _text(packet["answer"], "packet answer", 20000)
    allowed = _ids(
        case["allowed_evidence_ids"], "allowed source", 1, MAX_ALLOWED_SOURCES
    )
    expected = [sources[source_id] for source_id in allowed]
    packet_sources = _array(
        packet["source_snapshots"], "packet sources", 1, MAX_ALLOWED_SOURCES
    )
    if packet_sources != expected:
        raise TargetProjectionError("packet source view differs from approved case")
    texts = {source["evidence_id"]: source["text"] for source in expected}
    seen: set[tuple[str, int, int]] = set()
    for value in _array(packet["citation_spans"], "packet citations", 0, MAX_CITATIONS):
        citation = _object(value, "packet citation")
        _exact(citation, {"evidence_id", "quote", "start", "end"}, "packet citation")
        source_id = _id(citation["evidence_id"], "citation source ID")
        if source_id not in texts:
            raise TargetProjectionError("packet citation source is outside view")
        quote = _text(citation["quote"], "packet citation quote", MAX_SOURCE_TEXT)
        start, end = citation["start"], citation["end"]
        if (
            type(start) is not int
            or type(end) is not int
            or not 0 <= start < end <= len(texts[source_id])
            or texts[source_id][start:end] != quote
        ):
            raise TargetProjectionError("packet citation is not a source-exact span")
        key = (source_id, start, end)
        if key in seen:
            raise TargetProjectionError("duplicate packet citation")
        seen.add(key)


def derive_target_projection(
    *,
    corpus_bytes: bytes,
    source_pack_bytes: bytes,
    packet_bytes: bytes,
    approved_corpus_sha256: str,
    approved_source_pack_sha256: str,
    preverified_manifest_corpus_digest: str,
    preverified_manifest_source_pack_digest: str,
    preverified_packet_id: str,
    preverified_packet_sha256: str,
) -> bytes:
    """Derive canonical reviewer bytes from externally pinned raw inputs.

    A matching self-computed pin is not approval or signature verification.
    """
    for label, raw, pin, limit in (
        ("corpus", corpus_bytes, approved_corpus_sha256, MAX_INPUT_BYTES),
        (
            "source pack",
            source_pack_bytes,
            approved_source_pack_sha256,
            MAX_INPUT_BYTES,
        ),
        ("packet", packet_bytes, preverified_packet_sha256, MAX_PACKET_BYTES),
    ):
        if (
            not isinstance(raw, bytes)
            or len(raw) > limit
            or _hash(raw) != _digest(pin, f"{label} pin")
        ):
            raise TargetProjectionError(
                f"{label} bytes differ from independently pinned digest"
            )
    corpus = _read_object(corpus_bytes, "corpus", MAX_INPUT_BYTES)
    pack = _read_object(source_pack_bytes, "source pack", MAX_INPUT_BYTES)
    packet = _read_object(packet_bytes, "packet", MAX_PACKET_BYTES)
    corpus_digest = _hash(_canonical(corpus))
    source_digest = _hash(_canonical(pack))
    if corpus_digest != _digest(
        preverified_manifest_corpus_digest, "manifest corpus digest"
    ) or source_digest != _digest(
        preverified_manifest_source_pack_digest, "manifest source digest"
    ):
        raise TargetProjectionError(
            "approved inputs differ from preverified packet manifest"
        )
    sources = _source_index(pack)
    if corpus.get("source_pack_id") != pack["source_pack_id"]:
        raise TargetProjectionError("corpus names a different source pack")
    if (
        _digest(corpus.get("source_pack_digest"), "corpus source digest")
        != source_digest
    ):
        raise TargetProjectionError(
            "corpus source digest differs from approved source pack"
        )
    cases = _case_index(corpus, sources)
    case_id = _id(packet.get("case_id"), "packet case ID")
    if case_id not in cases:
        raise TargetProjectionError("packet case is not in approved corpus")
    case = cases[case_id]
    _validate_packet(packet, case, sources, preverified_packet_id)
    visible = {item["evidence_id"]: item["text"] for item in packet["source_snapshots"]}
    projection = {
        "schema_version": 1,
        "corpus_digest": corpus_digest,
        "source_pack_digest": source_digest,
        "packet_id": preverified_packet_id,
        "packet_sha256": preverified_packet_sha256,
        "case_id": case_id,
        "targets": _targets(case, visible),
    }
    raw_projection = _canonical(projection)
    if len(raw_projection) > MAX_PROJECTION_BYTES:
        raise TargetProjectionError("reviewer projection exceeds its byte bound")
    return raw_projection


def verify_target_projection(
    *,
    projection_bytes: bytes,
    preverified_review_projection_sha256: str,
    corpus_bytes: bytes,
    source_pack_bytes: bytes,
    packet_bytes: bytes,
    approved_corpus_sha256: str,
    approved_source_pack_sha256: str,
    preverified_manifest_corpus_digest: str,
    preverified_manifest_source_pack_digest: str,
    preverified_packet_id: str,
    preverified_packet_sha256: str,
) -> None:
    """Reject altered, noncanonical, stale, or extra reviewer-target fields."""
    if (
        not isinstance(projection_bytes, bytes)
        or len(projection_bytes) > MAX_PROJECTION_BYTES
        or _hash(projection_bytes)
        != _digest(preverified_review_projection_sha256, "review digest")
    ):
        raise TargetProjectionError("reviewer projection digest mismatch")
    expected = derive_target_projection(
        corpus_bytes=corpus_bytes,
        source_pack_bytes=source_pack_bytes,
        packet_bytes=packet_bytes,
        approved_corpus_sha256=approved_corpus_sha256,
        approved_source_pack_sha256=approved_source_pack_sha256,
        preverified_manifest_corpus_digest=preverified_manifest_corpus_digest,
        preverified_manifest_source_pack_digest=preverified_manifest_source_pack_digest,
        preverified_packet_id=preverified_packet_id,
        preverified_packet_sha256=preverified_packet_sha256,
    )
    if projection_bytes != expected:
        raise TargetProjectionError(
            "reviewer projection differs from approved derived targets"
        )
