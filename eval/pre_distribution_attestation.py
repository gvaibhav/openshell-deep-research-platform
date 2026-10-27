"""CR-0025 pre-distribution citation *binding* checks for synthetic/public runs.

This unused verifier returns no authorization token and never distributes a
packet or target. Inputs include restricted candidate-labeled attestation,
original artifact, extraction record, signature, and key material; callers
must keep them out of blind reviewer views and ordinary logs. The caller must
obtain raw input/key pins and expected cell IDs from independent registers,
not compute them from the files supplied in the same call. Matching local
values cannot establish human approval or the key's control-review role.

The fixed qualified OpenSSL profile only checks signature bytes with a pinned
public-key digest. It does not qualify key strength/algorithm, role separation,
validity or revocation; a distributor needs a separate approved key register.
This verifier also cannot establish original product-native extraction truth,
trusted signature time, a complete candidate-by-case matrix, held-FD packet
custody, reviewer-edge byte identity, delivery order, blind-safe answer text,
or source semantics. The distributor must compare the manifest packet set to
independently prepared completed assignments and dispositions before release.
Original artifact and extraction-record reads must be bounded at their ingress.
Those independent gates remain closed; successful return is never SEL proof.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from eval.blind_review.tool import BlindReviewError, _verify_detached_signature
from eval.target_projection import TargetProjectionError, derive_target_projection

DOMAIN = b"openshell-deep-research/pre-distribution-citation-attestation/v1\n"
MAX_ATTESTATION_BYTES = 32 * 1024
MAX_SIGNATURE_BYTES = 8 * 1024
MAX_PUBLIC_KEY_BYTES = 8 * 1024
MAX_PACKET_BYTES = 128 * 1024
MAX_INPUT_BYTES = 1024 * 1024
MAX_MANIFEST_BYTES = MAX_INPUT_BYTES
MAX_PACKETS = 128
MAX_CITATIONS = 32
ATTESTATION_FIELDS = {
    "schema_version",
    "attestation_type",
    "candidate_id",
    "case_id",
    "run_id",
    "packet_id",
    "packet_sha256",
    "packet_manifest_sha256",
    "corpus_digest",
    "source_pack_digest",
    "rubric_digest",
    "original_artifact_sha256",
    "extraction_record_sha256",
    "citation_count",
    "citation_spans_sha256",
    "decision",
    "control_reviewer_id",
    "submission_time_ref",
}
MANIFEST_FIELDS = {
    "schema_version",
    "cell_count",
    "packet_count",
    "corpus_digest",
    "source_pack_digest",
    "rubric_digest",
    "packets",
}
PACKET_FIELDS = {
    "schema_version",
    "packet_id",
    "case_id",
    "question",
    "answer",
    "source_snapshots",
    "citation_spans",
}
ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
PACKET_ID_RE = re.compile(r"bp-[0-9a-f]{32}\Z")
DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")


class PreDistributionAttestationError(ValueError):
    """Exact bytes or signed binding cannot satisfy the isolated contract."""


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
        raise PreDistributionAttestationError("invalid JSON value") from exc


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise PreDistributionAttestationError("duplicate JSON key")
        value[key] = item
    return value


def _reject_nonfinite(_: str) -> Any:
    raise PreDistributionAttestationError("nonfinite JSON number")


def _raw_bytes(value: Any, label: str, maximum: int | None = None) -> bytes:
    if not isinstance(value, bytes) or (maximum is not None and len(value) > maximum):
        raise PreDistributionAttestationError(f"{label} exceeds its byte bound")
    return value


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PreDistributionAttestationError(f"{label} must be an object")
    return value


def _read_object(raw: bytes, label: str, maximum: int) -> dict[str, Any]:
    _raw_bytes(raw, label, maximum)
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_keys,
            parse_constant=_reject_nonfinite,
        )
        _canonical(value)  # Reject overflowing floats and unpaired surrogates.
    except PreDistributionAttestationError:
        raise
    except (UnicodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise PreDistributionAttestationError(
            f"{label} is not valid UTF-8 JSON"
        ) from exc
    return _object(value, label)


def _exact(value: dict[str, Any], keys: set[str], label: str) -> None:
    if set(value) != keys:
        raise PreDistributionAttestationError(
            f"{label} has missing or unsupported fields"
        )


def _id(value: Any, label: str) -> str:
    if not isinstance(value, str) or ID_RE.fullmatch(value) is None:
        raise PreDistributionAttestationError(f"{label} has invalid syntax")
    return value


def _packet_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or PACKET_ID_RE.fullmatch(value) is None:
        raise PreDistributionAttestationError(f"{label} has invalid syntax")
    return value


def _digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or DIGEST_RE.fullmatch(value) is None:
        raise PreDistributionAttestationError(f"{label} must be SHA-256")
    return value


def _count(value: Any, label: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise PreDistributionAttestationError(f"{label} exceeds its count bound")
    return value


def _text(value: Any, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise PreDistributionAttestationError(f"{label} must be bounded nonempty text")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise PreDistributionAttestationError(
            f"{label} contains invalid Unicode"
        ) from exc
    return value


def _attestation(value: dict[str, Any]) -> None:
    decision = value.get("decision")
    if decision == "blocked":
        _exact(value, ATTESTATION_FIELDS | {"reason"}, "attestation")
        _text(value["reason"], "blocking reason", 2048)
    else:
        _exact(value, ATTESTATION_FIELDS, "attestation")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise PreDistributionAttestationError("unsupported attestation version")
    if value["attestation_type"] != "pre_distribution_citation_attestation":
        raise PreDistributionAttestationError("unsupported attestation type")
    for field in ("candidate_id", "case_id", "run_id", "control_reviewer_id"):
        _id(value[field], field)
    _packet_id(value["packet_id"], "attested packet ID")
    for field in (
        "packet_sha256",
        "packet_manifest_sha256",
        "corpus_digest",
        "source_pack_digest",
        "rubric_digest",
        "original_artifact_sha256",
        "extraction_record_sha256",
        "citation_spans_sha256",
    ):
        _digest(value[field], field)
    _count(value["citation_count"], "citation count", 0, MAX_CITATIONS)
    _text(value["submission_time_ref"], "submission time reference", 512)
    if decision not in ("corroborated", "blocked"):
        raise PreDistributionAttestationError("unsupported attestation decision")


def _write_private(path: Path, raw: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    with os.fdopen(os.open(path, flags, 0o600), "wb") as handle:
        handle.write(raw)


def _verify_control_signature(
    attestation_bytes: bytes,
    detached_signature_bytes: bytes,
    control_public_key_bytes: bytes,
    expected_control_public_key_sha256: str,
) -> None:
    _raw_bytes(detached_signature_bytes, "detached signature", MAX_SIGNATURE_BYTES)
    _raw_bytes(control_public_key_bytes, "control public key", MAX_PUBLIC_KEY_BYTES)
    if (
        not detached_signature_bytes
        or not control_public_key_bytes
        or _hash(control_public_key_bytes)
        != _digest(expected_control_public_key_sha256, "control public-key pin")
    ):
        raise PreDistributionAttestationError(
            "control signature or public-key pin is invalid"
        )
    try:
        with tempfile.TemporaryDirectory(
            prefix="pre-distribution-binding-"
        ) as directory:
            key_path = Path(directory) / "public.pem"
            signature_path = Path(directory) / "signature.sig"
            _write_private(key_path, control_public_key_bytes)
            _write_private(signature_path, detached_signature_bytes)
            _verify_detached_signature(
                payload_raw=DOMAIN + attestation_bytes,
                signature_path=signature_path,
                public_key_path=key_path,
                trusted_key_sha256=expected_control_public_key_sha256,
                label="pre-distribution citation attestation",
            )
    except (BlindReviewError, OSError) as exc:
        raise PreDistributionAttestationError(
            "control signature verification failed"
        ) from exc


def _check_manifest(
    manifest: dict[str, Any], packet_id: str, packet_sha256: str
) -> None:
    _exact(manifest, MANIFEST_FIELDS, "packet manifest")
    if type(manifest["schema_version"]) is not int or manifest["schema_version"] != 2:
        raise PreDistributionAttestationError("unsupported packet manifest version")
    cell_count = _count(manifest["cell_count"], "manifest cell count", 1, 240)
    packet_count = _count(
        manifest["packet_count"], "manifest packet count", 0, MAX_PACKETS
    )
    records = manifest["packets"]
    if (
        not isinstance(records, list)
        or len(records) != packet_count
        or packet_count > cell_count
    ):
        raise PreDistributionAttestationError(
            "manifest packet count or list is inconsistent"
        )
    ids: set[str] = set()
    hashes: set[str] = set()
    found = False
    for item in records:
        record = _object(item, "manifest packet record")
        _exact(record, {"packet_id", "packet_sha256"}, "manifest packet record")
        record_id = _packet_id(record["packet_id"], "manifest packet ID")
        record_sha = _digest(record["packet_sha256"], "manifest packet hash")
        if record_id in ids or record_sha in hashes:
            raise PreDistributionAttestationError("duplicate manifest packet identity")
        ids.add(record_id)
        hashes.add(record_sha)
        if record_id == packet_id:
            found = record_sha == packet_sha256
    if not found:
        raise PreDistributionAttestationError("attested packet is absent from manifest")
    for field in ("corpus_digest", "source_pack_digest", "rubric_digest"):
        _digest(manifest[field], f"manifest {field}")


def _check_raw_pin(raw: bytes, expected_sha256: str, label: str, maximum: int) -> None:
    _raw_bytes(raw, label, maximum)
    if _hash(raw) != _digest(expected_sha256, f"{label} raw pin"):
        raise PreDistributionAttestationError(
            f"{label} differs from its external raw pin"
        )


def verify_pre_distribution_attestation(
    *,
    attestation_bytes: bytes,
    detached_signature_bytes: bytes,
    control_public_key_bytes: bytes,
    expected_control_public_key_sha256: str,
    expected_control_reviewer_id: str,
    expected_candidate_id: str,
    expected_case_id: str,
    expected_run_id: str,
    expected_packet_id: str,
    packet_bytes: bytes,
    packet_manifest_bytes: bytes,
    corpus_bytes: bytes,
    source_pack_bytes: bytes,
    rubric_bytes: bytes,
    approved_corpus_sha256: str,
    approved_source_pack_sha256: str,
    approved_rubric_sha256: str,
    original_artifact_bytes: bytes,
    extraction_record_bytes: bytes,
) -> None:
    """Verify an exact signed byte binding; successful return conveys no approval.

    The caller must separately qualify the signing key and approval pins,
    establish full-matrix and timestamp evidence, then distribute the same
    held-FD packet bytes and check their receipt at the reviewer edge.
    """
    attestation = _read_object(
        attestation_bytes, "pre-distribution attestation", MAX_ATTESTATION_BYTES
    )
    _attestation(attestation)
    _verify_control_signature(
        attestation_bytes,
        detached_signature_bytes,
        control_public_key_bytes,
        expected_control_public_key_sha256,
    )
    for field, expected in (
        ("candidate_id", _id(expected_candidate_id, "expected candidate ID")),
        ("case_id", _id(expected_case_id, "expected case ID")),
        ("run_id", _id(expected_run_id, "expected run ID")),
        (
            "control_reviewer_id",
            _id(expected_control_reviewer_id, "expected control reviewer ID"),
        ),
        ("packet_id", _packet_id(expected_packet_id, "expected packet ID")),
    ):
        if attestation[field] != expected:
            raise PreDistributionAttestationError(f"{field} differs from expected cell")
    if attestation["decision"] != "corroborated":
        raise PreDistributionAttestationError("blocking citation decision")

    _check_raw_pin(corpus_bytes, approved_corpus_sha256, "corpus", MAX_INPUT_BYTES)
    _check_raw_pin(
        source_pack_bytes, approved_source_pack_sha256, "source pack", MAX_INPUT_BYTES
    )
    _check_raw_pin(rubric_bytes, approved_rubric_sha256, "rubric", MAX_INPUT_BYTES)
    _raw_bytes(packet_bytes, "packet", MAX_PACKET_BYTES)
    _raw_bytes(packet_manifest_bytes, "packet manifest", MAX_MANIFEST_BYTES)
    _raw_bytes(original_artifact_bytes, "original artifact")
    _raw_bytes(extraction_record_bytes, "extraction record")
    for raw, field in (
        (packet_bytes, "packet_sha256"),
        (packet_manifest_bytes, "packet_manifest_sha256"),
        (original_artifact_bytes, "original_artifact_sha256"),
        (extraction_record_bytes, "extraction_record_sha256"),
    ):
        if _hash(raw) != attestation[field]:
            raise PreDistributionAttestationError(
                f"{field} differs from supplied bytes"
            )

    corpus = _read_object(corpus_bytes, "corpus", MAX_INPUT_BYTES)
    source_pack = _read_object(source_pack_bytes, "source pack", MAX_INPUT_BYTES)
    rubric = _read_object(rubric_bytes, "rubric", MAX_INPUT_BYTES)
    manifest = _read_object(
        packet_manifest_bytes, "packet manifest", MAX_MANIFEST_BYTES
    )
    packet = _read_object(packet_bytes, "packet", MAX_PACKET_BYTES)
    _check_manifest(manifest, attestation["packet_id"], attestation["packet_sha256"])
    for field, source in (
        ("corpus_digest", corpus),
        ("source_pack_digest", source_pack),
        ("rubric_digest", rubric),
    ):
        actual_digest = _hash(_canonical(source))
        if actual_digest != manifest[field] or manifest[field] != attestation[field]:
            raise PreDistributionAttestationError(
                f"{field} differs from approved input"
            )
    # An embedded approval marker is only a consistency check, never evidence
    # that the separately supplied rubric raw pin was approved by a human.
    approval = rubric.get("approval")
    if not isinstance(approval, dict) or approval.get("status") != "approved":
        raise PreDistributionAttestationError("rubric approval marker is absent")
    _exact(packet, PACKET_FIELDS, "packet")
    if type(packet["schema_version"]) is not int or packet["schema_version"] != 1:
        raise PreDistributionAttestationError("unsupported packet version")
    if (
        packet["packet_id"] != attestation["packet_id"]
        or packet["case_id"] != attestation["case_id"]
        or packet["case_id"] != expected_case_id
    ):
        raise PreDistributionAttestationError(
            "packet ID or case differs from signed cell"
        )
    citations = packet["citation_spans"]
    if not isinstance(citations, list) or len(citations) > MAX_CITATIONS:
        raise PreDistributionAttestationError("packet citation count exceeds its bound")
    if (
        len(citations) != attestation["citation_count"]
        or _hash(_canonical(citations)) != attestation["citation_spans_sha256"]
    ):
        raise PreDistributionAttestationError("ordered packet citation digest differs")

    # These are already signed manifest/packet values after the checks above.
    # The projection is computed solely to reuse its strict approved-case and
    # source-span validator; its bytes are discarded and never distributed.
    try:
        derive_target_projection(
            corpus_bytes=corpus_bytes,
            source_pack_bytes=source_pack_bytes,
            packet_bytes=packet_bytes,
            approved_corpus_sha256=approved_corpus_sha256,
            approved_source_pack_sha256=approved_source_pack_sha256,
            preverified_manifest_corpus_digest=manifest["corpus_digest"],
            preverified_manifest_source_pack_digest=manifest["source_pack_digest"],
            preverified_packet_id=attestation["packet_id"],
            preverified_packet_sha256=attestation["packet_sha256"],
        )
    except TargetProjectionError as exc:
        raise PreDistributionAttestationError(
            "packet is outside approved case view"
        ) from exc
