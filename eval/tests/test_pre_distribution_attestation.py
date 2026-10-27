"""CR-0025 byte-boundary tests with synthetic inputs and temporary signing keys.

These tests exercise a local verifier, not product-native extraction, an
independent signer, trusted signing time, held-FD delivery, or SEL readiness.
"""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any, ClassVar
from unittest.mock import patch

from jsonschema import Draft202012Validator, ValidationError

from eval.blind_review import tool as blind_tool_module
from eval.pre_distribution_attestation import (
    PreDistributionAttestationError,
    verify_pre_distribution_attestation,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas/pre-distribution-citation-attestation.schema.json"
OPENSSL = Path("/usr/bin/openssl")
DOMAIN = b"openshell-deep-research/pre-distribution-citation-attestation/v1\n"
PINNED_DRAFT_CORPUS_RAW = (
    "ce3412990a8f9daa24ce682b170b2cbc792130a424ce93b69d7725c578f7d615"
)
PINNED_DRAFT_SOURCE_RAW = (
    "ecba311adb883bda74bec5e98998246f03be6463bfc3e4960a55add8239945f6"
)
PINNED_DRAFT_RUBRIC_RAW = (
    "7056a9bc9efc922d0bce6e80645d3ca7ce4cab093257af34100e2e281c37846a"
)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def encoded(value: object) -> bytes:
    return canonical(value) + b"\n"


class PreDistributionAttestationTests(unittest.TestCase):
    key_directory: ClassVar[tempfile.TemporaryDirectory[str]]
    private_key: ClassVar[Path]
    public_key: ClassVar[bytes]
    wrong_private_key: ClassVar[Path]
    wrong_public_key: ClassVar[bytes]
    corpus: ClassVar[dict[str, Any]]
    sources: ClassVar[dict[str, Any]]
    rubric: ClassVar[dict[str, Any]]
    packet: ClassVar[dict[str, Any]]
    manifest: ClassVar[dict[str, Any]]
    attestation: ClassVar[dict[str, Any]]

    @classmethod
    def setUpClass(cls) -> None:
        # Test-only pin; the application verifier remains separately qualified.
        cls.enterClassContext(
            patch.object(
                blind_tool_module,
                "TRUSTED_VERIFIER_SHA256",
                digest(OPENSSL.read_bytes()),
            )
        )
        cls.key_directory = tempfile.TemporaryDirectory(prefix="synthetic-pre-attest-")
        cls.addClassCleanup(cls.key_directory.cleanup)
        directory = Path(cls.key_directory.name)
        cls.private_key = directory / "synthetic-control-private.pem"
        cls.wrong_private_key = directory / "unregistered-private.pem"
        cls.public_key = cls._make_key(cls.private_key)
        cls.wrong_public_key = cls._make_key(cls.wrong_private_key)

        draft_corpus = (ROOT / "corpus/v1/cases.json").read_bytes()
        draft_sources = (ROOT / "corpus/v1/sources.json").read_bytes()
        draft_rubric = (ROOT / "corpus/v1/rubric.json").read_bytes()
        assert digest(draft_corpus) == PINNED_DRAFT_CORPUS_RAW
        assert digest(draft_sources) == PINNED_DRAFT_SOURCE_RAW
        assert digest(draft_rubric) == PINNED_DRAFT_RUBRIC_RAW
        cls.corpus = copy.deepcopy(json.loads(draft_corpus))
        cls.sources = copy.deepcopy(json.loads(draft_sources))
        cls.rubric = copy.deepcopy(json.loads(draft_rubric))
        cls.corpus["source_pack_digest"] = digest(canonical(cls.sources))
        approval = {
            "status": "approved",
            "reviewer_id": "synthetic-input-approver",
            "reviewed_at": "2026-10-26T09:00:00Z",
        }
        cls.corpus["approval"] = approval
        cls.rubric["approval"] = approval

        case = next(row for row in cls.corpus["cases"] if row["case_id"] == "case-02")
        source_by_id = {row["evidence_id"]: row for row in cls.sources["sources"]}
        snapshots = [
            {
                "evidence_id": source_id,
                "origin": source_by_id[source_id]["origin"],
                "text": source_by_id[source_id]["text"],
            }
            for source_id in case["allowed_evidence_ids"]
        ]
        citations = []
        for target in case["expected_citation_spans"]:
            source_id = target["evidence_id"]
            quote = target["quote"]
            start = source_by_id[source_id]["text"].index(quote)
            citations.append(
                {
                    "evidence_id": source_id,
                    "quote": quote,
                    "start": start,
                    "end": start + len(quote),
                }
            )
        cls.packet = {
            "schema_version": 1,
            "packet_id": "bp-" + "a" * 32,
            "case_id": case["case_id"],
            "question": case["question"],
            "answer": "The synthetic plan and release log have different dates.",
            "source_snapshots": snapshots,
            "citation_spans": citations,
        }
        cls.manifest = {
            "schema_version": 2,
            "cell_count": 1,
            "packet_count": 1,
            "corpus_digest": digest(canonical(cls.corpus)),
            "source_pack_digest": digest(canonical(cls.sources)),
            "rubric_digest": digest(canonical(cls.rubric)),
            "packets": [
                {
                    "packet_id": cls.packet["packet_id"],
                    "packet_sha256": digest(encoded(cls.packet)),
                }
            ],
        }
        cls.attestation = {
            "schema_version": 1,
            "attestation_type": "pre_distribution_citation_attestation",
            "candidate_id": "synthetic_candidate",
            "case_id": case["case_id"],
            "run_id": "synthetic_run_001",
            "packet_id": cls.packet["packet_id"],
            "packet_sha256": digest(encoded(cls.packet)),
            "packet_manifest_sha256": digest(encoded(cls.manifest)),
            "corpus_digest": cls.manifest["corpus_digest"],
            "source_pack_digest": cls.manifest["source_pack_digest"],
            "rubric_digest": cls.manifest["rubric_digest"],
            "original_artifact_sha256": digest(
                b"synthetic retained candidate output\n"
            ),
            "extraction_record_sha256": digest(
                b"synthetic versioned extraction record\n"
            ),
            "citation_count": len(citations),
            "citation_spans_sha256": digest(canonical(citations)),
            "decision": "corroborated",
            "control_reviewer_id": "synthetic_control_reviewer",
            "submission_time_ref": "synthetic-append-only-log:entry-001",
        }

    @staticmethod
    def _make_key(private_path: Path) -> bytes:
        public_path = private_path.with_suffix(".pub.pem")
        subprocess.run(
            [
                str(OPENSSL),
                "genpkey",
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
        return public_path.read_bytes()

    def _sign(
        self, raw: bytes, *, private_key: Path | None = None, domain: bool = True
    ) -> bytes:
        signed = subprocess.run(
            [
                str(OPENSSL),
                "dgst",
                "-sha256",
                "-sign",
                str(private_key or self.private_key),
            ],
            input=(DOMAIN if domain else b"") + raw,
            check=True,
            capture_output=True,
        )
        return signed.stdout

    def _valid(self) -> dict[str, Any]:
        attestation_bytes = encoded(self.attestation)
        corpus_bytes = encoded(self.corpus)
        source_pack_bytes = encoded(self.sources)
        rubric_bytes = encoded(self.rubric)
        return {
            "attestation_bytes": attestation_bytes,
            "detached_signature_bytes": self._sign(attestation_bytes),
            "control_public_key_bytes": self.public_key,
            "expected_control_public_key_sha256": digest(self.public_key),
            "expected_control_reviewer_id": self.attestation["control_reviewer_id"],
            "expected_candidate_id": self.attestation["candidate_id"],
            "expected_case_id": self.attestation["case_id"],
            "expected_run_id": self.attestation["run_id"],
            "expected_packet_id": self.attestation["packet_id"],
            "packet_bytes": encoded(self.packet),
            "packet_manifest_bytes": encoded(self.manifest),
            "corpus_bytes": corpus_bytes,
            "source_pack_bytes": source_pack_bytes,
            "rubric_bytes": rubric_bytes,
            "approved_corpus_sha256": digest(corpus_bytes),
            "approved_source_pack_sha256": digest(source_pack_bytes),
            "approved_rubric_sha256": digest(rubric_bytes),
            "original_artifact_bytes": b"synthetic retained candidate output\n",
            "extraction_record_bytes": b"synthetic versioned extraction record\n",
        }

    def _resign(self, values: dict[str, Any], attestation: dict[str, Any]) -> None:
        values["attestation_bytes"] = encoded(attestation)
        values["detached_signature_bytes"] = self._sign(values["attestation_bytes"])

    def _rebind(
        self,
        values: dict[str, Any],
        packet: dict[str, Any],
        manifest: dict[str, Any],
        attestation: dict[str, Any],
        *,
        citations: bool,
    ) -> None:
        values["packet_bytes"] = encoded(packet)
        manifest["packets"][0]["packet_sha256"] = digest(values["packet_bytes"])
        values["packet_manifest_bytes"] = encoded(manifest)
        attestation["packet_sha256"] = digest(values["packet_bytes"])
        attestation["packet_manifest_sha256"] = digest(values["packet_manifest_bytes"])
        if citations:
            attestation["citation_count"] = len(packet["citation_spans"])
            attestation["citation_spans_sha256"] = digest(
                canonical(packet["citation_spans"])
            )
        self._resign(values, attestation)

    def test_draft_input_pins_are_explicit_and_in_memory_approval_is_only_a_double(
        self,
    ) -> None:
        self.assertEqual(
            json.loads((ROOT / "corpus/v1/cases.json").read_bytes())["approval"],
            {"status": "pending"},
        )
        values = self._valid()
        self.assertNotEqual(values["approved_corpus_sha256"], PINNED_DRAFT_CORPUS_RAW)
        self.assertNotEqual(values["approved_rubric_sha256"], PINNED_DRAFT_RUBRIC_RAW)
        self.assertNotIn(b"synthetic_candidate", values["packet_bytes"])
        # Successful local matching yields no approval token or delivery instruction.
        verify_pre_distribution_attestation(**values)

    def test_schema_has_exact_fields_and_conditional_block_reason(self) -> None:
        schema = json.loads(SCHEMA.read_bytes())
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        validator.validate(self.attestation)
        blocked = {
            **self.attestation,
            "decision": "blocked",
            "reason": "synthetic mismatch",
        }
        validator.validate(blocked)
        for mutation in (
            lambda a: a.pop("candidate_id"),
            lambda a: a.__setitem__("extra", "unsupported"),
            lambda a: a.__setitem__("reason", "not allowed for corroborated"),
            lambda a: a.__setitem__("decision", "blocked"),
            lambda a: a.__setitem__("schema_version", True),
            lambda a: a.__setitem__("citation_count", 33),
            lambda a: a.__setitem__("candidate_id", "synthetic_candidate\n"),
            lambda a: a.__setitem__("packet_id", a["packet_id"] + "\n"),
            lambda a: a.__setitem__("packet_sha256", a["packet_sha256"] + "\n"),
        ):
            with self.subTest(mutation=mutation):
                altered = copy.deepcopy(self.attestation)
                mutation(altered)
                with self.assertRaises(ValidationError):
                    validator.validate(altered)

    def test_signed_integral_float_spellings_are_denied_by_runtime(self) -> None:
        # JSON Schema calls 1.0 an integer; the exact-byte verifier requires
        # a JSON integer spelling before any delivery decision can be made.
        schema = json.loads(SCHEMA.read_bytes())
        validator = Draft202012Validator(schema)
        for field, value in (
            ("schema_version", 1.0),
            ("citation_count", float(self.attestation["citation_count"])),
        ):
            with self.subTest(field=field):
                attestation = copy.deepcopy(self.attestation)
                attestation[field] = value
                validator.validate(attestation)
                values = self._valid()
                self._resign(values, attestation)
                with self.assertRaises(PreDistributionAttestationError):
                    verify_pre_distribution_attestation(**values)

    def test_resigned_wrong_missing_extra_and_blocked_attestations_deny(self) -> None:
        mutations = (
            lambda a: a.pop("candidate_id"),
            lambda a: a.__setitem__("extra", "unsupported"),
            lambda a: a.__setitem__("attestation_type", "other"),
            lambda a: a.__setitem__("schema_version", True),
            lambda a: a.__setitem__("reason", "not allowed"),
            lambda a: a.update(decision="blocked", reason="synthetic source mismatch"),
            lambda a: a.__setitem__("citation_spans_sha256", "0" * 64),
            lambda a: a.__setitem__("citation_count", 0),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                values = self._valid()
                attestation = copy.deepcopy(self.attestation)
                mutation(attestation)
                self._resign(values, attestation)
                with self.assertRaises(PreDistributionAttestationError):
                    verify_pre_distribution_attestation(**values)

    def test_duplicate_keys_nonfinite_and_invalid_utf8_deny(self) -> None:
        for raw in (
            b'{"decision":"corroborated","decision":"corroborated"}',
            b'{"value":NaN}',
            b'{"value":1e999}',
            b'{"value":"\xff"}',
        ):
            with self.subTest(raw=raw):
                values = self._valid()
                values["attestation_bytes"] = raw
                values["detached_signature_bytes"] = self._sign(raw)
                with self.assertRaises(PreDistributionAttestationError):
                    verify_pre_distribution_attestation(**values)

    def test_exact_32_kib_attestation_accepted_and_next_byte_denied(self) -> None:
        values = self._valid()
        exactly = values["attestation_bytes"].rstrip() + b" " * (
            32 * 1024 - len(values["attestation_bytes"].rstrip())
        )
        self.assertEqual(len(exactly), 32 * 1024)
        values["attestation_bytes"] = exactly
        values["detached_signature_bytes"] = self._sign(exactly)
        verify_pre_distribution_attestation(**values)
        values["attestation_bytes"] += b" "
        with self.assertRaises(PreDistributionAttestationError):
            verify_pre_distribution_attestation(**values)

    def test_signature_is_domain_separated_exact_and_key_pinned(self) -> None:
        values = self._valid()
        values["detached_signature_bytes"] = self._sign(
            values["attestation_bytes"], domain=False
        )
        with self.assertRaises(PreDistributionAttestationError):
            verify_pre_distribution_attestation(**values)
        values = self._valid()
        values["attestation_bytes"] += b" "
        with self.assertRaises(PreDistributionAttestationError):
            verify_pre_distribution_attestation(**values)
        values = self._valid()
        values["detached_signature_bytes"] = self._sign(
            values["attestation_bytes"], private_key=self.wrong_private_key
        )
        values["control_public_key_bytes"] = self.wrong_public_key
        with self.assertRaises(PreDistributionAttestationError):
            verify_pre_distribution_attestation(**values)
        values = self._valid()
        values["detached_signature_bytes"] = b"x" * (8 * 1024 + 1)
        with self.assertRaises(PreDistributionAttestationError):
            verify_pre_distribution_attestation(**values)

    def test_expected_identities_must_be_supplied_outside_signed_object(self) -> None:
        for field in (
            "expected_candidate_id",
            "expected_case_id",
            "expected_run_id",
            "expected_control_reviewer_id",
            "expected_packet_id",
        ):
            with self.subTest(field=field):
                values = self._valid()
                values[field] = "wrong_external_expectation"
                with self.assertRaises(PreDistributionAttestationError):
                    verify_pre_distribution_attestation(**values)

    def test_packet_and_complete_manifest_raw_hashes_and_membership_deny_changes(
        self,
    ) -> None:
        for field in ("packet_bytes", "packet_manifest_bytes"):
            with self.subTest(field=field):
                values = self._valid()
                values[field] += b" "
                with self.assertRaises(PreDistributionAttestationError):
                    verify_pre_distribution_attestation(**values)
        values = self._valid()
        manifest = copy.deepcopy(self.manifest)
        manifest["packets"][0]["packet_id"] = "bp-" + "b" * 32
        values["packet_manifest_bytes"] = encoded(manifest)
        attestation = copy.deepcopy(self.attestation)
        attestation["packet_manifest_sha256"] = digest(values["packet_manifest_bytes"])
        self._resign(values, attestation)
        with self.assertRaises(PreDistributionAttestationError):
            verify_pre_distribution_attestation(**values)

        # The manifest is signed as a whole, yet its member hash must still
        # agree with the attested and supplied packet bytes.
        values = self._valid()
        manifest = copy.deepcopy(self.manifest)
        manifest["packets"][0]["packet_sha256"] = "0" * 64
        values["packet_manifest_bytes"] = encoded(manifest)
        attestation = copy.deepcopy(self.attestation)
        attestation["packet_manifest_sha256"] = digest(values["packet_manifest_bytes"])
        self._resign(values, attestation)
        with self.assertRaises(PreDistributionAttestationError):
            verify_pre_distribution_attestation(**values)

    def test_packet_case_must_equal_attestation_and_expected_approved_case(
        self,
    ) -> None:
        values = self._valid()
        case = next(row for row in self.corpus["cases"] if row["case_id"] == "case-03")
        source_by_id = {row["evidence_id"]: row for row in self.sources["sources"]}
        packet = copy.deepcopy(self.packet)
        packet["case_id"] = case["case_id"]
        packet["question"] = case["question"]
        packet["source_snapshots"] = [
            {
                "evidence_id": source_id,
                "origin": source_by_id[source_id]["origin"],
                "text": source_by_id[source_id]["text"],
            }
            for source_id in case["allowed_evidence_ids"]
        ]
        packet["citation_spans"] = []
        self._rebind(
            values,
            packet,
            copy.deepcopy(self.manifest),
            copy.deepcopy(self.attestation),
            citations=True,
        )
        # This is a valid approved case view for case-03, so a verifier that
        # merely chooses packet.case_id would otherwise admit the wrong cell.
        with self.assertRaises(PreDistributionAttestationError):
            verify_pre_distribution_attestation(**values)

    def test_manifest_duplicate_ids_count_mismatch_and_129_packets_deny(self) -> None:
        variants = []
        duplicate = copy.deepcopy(self.manifest)
        duplicate["packets"].append(copy.deepcopy(duplicate["packets"][0]))
        duplicate["packet_count"] = duplicate["cell_count"] = 2
        variants.append(duplicate)
        count_mismatch = copy.deepcopy(self.manifest)
        count_mismatch["packet_count"] = 2
        variants.append(count_mismatch)
        too_many = self._many_packet_manifest(129)
        variants.append(too_many)
        for manifest in variants:
            with self.subTest(packet_count=manifest["packet_count"]):
                values = self._valid()
                values["packet_manifest_bytes"] = encoded(manifest)
                attestation = copy.deepcopy(self.attestation)
                attestation["packet_manifest_sha256"] = digest(
                    values["packet_manifest_bytes"]
                )
                self._resign(values, attestation)
                with self.assertRaises(PreDistributionAttestationError):
                    verify_pre_distribution_attestation(**values)

    def test_duplicate_non_target_manifest_id_or_hash_denies(self) -> None:
        for field in ("packet_id", "packet_sha256"):
            with self.subTest(field=field):
                values = self._valid()
                manifest = self._many_packet_manifest(3)
                manifest["packets"][2][field] = manifest["packets"][1][field]
                values["packet_manifest_bytes"] = encoded(manifest)
                attestation = copy.deepcopy(self.attestation)
                attestation["packet_manifest_sha256"] = digest(
                    values["packet_manifest_bytes"]
                )
                self._resign(values, attestation)
                with self.assertRaises(PreDistributionAttestationError):
                    verify_pre_distribution_attestation(**values)

    def _many_packet_manifest(self, count: int) -> dict[str, Any]:
        manifest = copy.deepcopy(self.manifest)
        manifest["cell_count"] = manifest["packet_count"] = count
        manifest["packets"] += [
            {
                "packet_id": "bp-" + f"{index:032x}",
                "packet_sha256": digest(f"synthetic-other-{index}".encode()),
            }
            for index in range(1, count)
        ]
        return manifest

    def test_128_packet_manifest_bound_accepts_target_membership_only(self) -> None:
        values = self._valid()
        manifest = self._many_packet_manifest(128)
        values["packet_manifest_bytes"] = encoded(manifest)
        attestation = copy.deepcopy(self.attestation)
        attestation["packet_manifest_sha256"] = digest(values["packet_manifest_bytes"])
        self._resign(values, attestation)
        # Other packet bytes are not supplied here; each needs its own gate.
        verify_pre_distribution_attestation(**values)

    def test_raw_input_pins_and_manifest_canonical_digests_are_independent_checks(
        self,
    ) -> None:
        for field, pin in (
            ("corpus_bytes", "approved_corpus_sha256"),
            ("source_pack_bytes", "approved_source_pack_sha256"),
            ("rubric_bytes", "approved_rubric_sha256"),
        ):
            with self.subTest(field=field):
                values = self._valid()
                values[field] += b" "
                with self.assertRaises(PreDistributionAttestationError):
                    verify_pre_distribution_attestation(**values)
                values = self._valid()
                values[pin] = "0" * 64
                with self.assertRaises(PreDistributionAttestationError):
                    verify_pre_distribution_attestation(**values)
        for field in ("corpus_digest", "source_pack_digest", "rubric_digest"):
            with self.subTest(field=field):
                values = self._valid()
                manifest = copy.deepcopy(self.manifest)
                manifest[field] = "0" * 64
                values["packet_manifest_bytes"] = encoded(manifest)
                attestation = copy.deepcopy(self.attestation)
                attestation[field] = "0" * 64
                attestation["packet_manifest_sha256"] = digest(
                    values["packet_manifest_bytes"]
                )
                self._resign(values, attestation)
                with self.assertRaises(PreDistributionAttestationError):
                    verify_pre_distribution_attestation(**values)

    def test_pending_approval_marker_denies_even_with_matching_self_pins(self) -> None:
        values = self._valid()
        corpus = copy.deepcopy(self.corpus)
        corpus["approval"] = {"status": "pending"}
        values["corpus_bytes"] = encoded(corpus)
        values["approved_corpus_sha256"] = digest(values["corpus_bytes"])
        manifest = copy.deepcopy(self.manifest)
        manifest["corpus_digest"] = digest(canonical(corpus))
        values["packet_manifest_bytes"] = encoded(manifest)
        attestation = copy.deepcopy(self.attestation)
        attestation["corpus_digest"] = manifest["corpus_digest"]
        attestation["packet_manifest_sha256"] = digest(values["packet_manifest_bytes"])
        self._resign(values, attestation)
        with self.assertRaises(PreDistributionAttestationError):
            verify_pre_distribution_attestation(**values)

    def test_original_and_extraction_digests_bind_separately_supplied_bytes(
        self,
    ) -> None:
        for field in ("original_artifact_bytes", "extraction_record_bytes"):
            with self.subTest(field=field):
                values = self._valid()
                values[field] += b"changed"
                with self.assertRaises(PreDistributionAttestationError):
                    verify_pre_distribution_attestation(**values)

    def test_changed_reordered_or_added_citation_denies_with_resigned_hashes(
        self,
    ) -> None:
        def changed(spans: list[dict[str, Any]]) -> None:
            spans[0]["quote"] = "planned for 2026-04-10"
            spans[0]["start"] += 1
            spans[0]["end"] += 1

        def reordered(spans: list[dict[str, Any]]) -> None:
            spans.reverse()

        def added(spans: list[dict[str, Any]]) -> None:
            text = self.packet["source_snapshots"][1]["text"]
            quote = "This supersedes the March plan."
            start = text.index(quote)
            spans.append(
                {
                    "evidence_id": "pub-launch-final",
                    "quote": quote,
                    "start": start,
                    "end": start + len(quote),
                }
            )

        for mutation in (changed, reordered, added):
            with self.subTest(mutation=mutation):
                values = self._valid()
                packet = copy.deepcopy(self.packet)
                mutation(packet["citation_spans"])
                self._rebind(
                    values,
                    packet,
                    copy.deepcopy(self.manifest),
                    copy.deepcopy(self.attestation),
                    citations=False,
                )
                with self.assertRaises(PreDistributionAttestationError):
                    verify_pre_distribution_attestation(**values)

    def test_signed_out_of_view_bad_span_and_duplicate_citation_deny(self) -> None:
        source_by_id = {row["evidence_id"]: row for row in self.sources["sources"]}

        def out_of_view(spans: list[dict[str, Any]]) -> None:
            quote = "costs 15 credits per job"
            source = source_by_id["pub-pricing-apr"]["text"]
            start = source.index(quote)
            spans[0] = {
                "evidence_id": "pub-pricing-apr",
                "quote": quote,
                "start": start,
                "end": start + len(quote),
            }

        def bad_span(spans: list[dict[str, Any]]) -> None:
            spans[0]["start"] += 1
            spans[0]["end"] += 1

        def duplicate(spans: list[dict[str, Any]]) -> None:
            spans.append(copy.deepcopy(spans[0]))

        for mutation in (out_of_view, bad_span, duplicate):
            with self.subTest(mutation=mutation):
                values = self._valid()
                packet = copy.deepcopy(self.packet)
                mutation(packet["citation_spans"])
                self._rebind(
                    values,
                    packet,
                    copy.deepcopy(self.manifest),
                    copy.deepcopy(self.attestation),
                    citations=True,
                )
                with self.assertRaises(PreDistributionAttestationError):
                    verify_pre_distribution_attestation(**values)

    def test_signed_question_source_view_order_and_label_field_deny(self) -> None:
        for field in ("question", "source_snapshots", "source_order", "candidate_id"):
            with self.subTest(field=field):
                values = self._valid()
                packet = copy.deepcopy(self.packet)
                if field == "question":
                    packet["question"] = "synthetic substituted question"
                elif field == "source_snapshots":
                    packet[field][0]["text"] = "synthetic substituted source"
                elif field == "source_order":
                    packet["source_snapshots"].reverse()
                else:
                    packet[field] = "synthetic_candidate"
                self._rebind(
                    values,
                    packet,
                    copy.deepcopy(self.manifest),
                    copy.deepcopy(self.attestation),
                    citations=True,
                )
                with self.assertRaises(PreDistributionAttestationError):
                    verify_pre_distribution_attestation(**values)

    def test_duplicate_json_keys_in_packet_or_manifest_deny_after_resigning(
        self,
    ) -> None:
        values = self._valid()
        packet_raw = (
            b'{"packet_id":"'
            + self.packet["packet_id"].encode()
            + b'",'
            + values["packet_bytes"][1:]
        )
        values["packet_bytes"] = packet_raw
        manifest = copy.deepcopy(self.manifest)
        manifest["packets"][0]["packet_sha256"] = digest(packet_raw)
        values["packet_manifest_bytes"] = encoded(manifest)
        attestation = copy.deepcopy(self.attestation)
        attestation["packet_sha256"] = digest(packet_raw)
        attestation["packet_manifest_sha256"] = digest(values["packet_manifest_bytes"])
        self._resign(values, attestation)
        with self.assertRaisesRegex(
            PreDistributionAttestationError, "duplicate JSON key"
        ):
            verify_pre_distribution_attestation(**values)

        values = self._valid()
        manifest_raw = b'{"packet_count":1,' + values["packet_manifest_bytes"][1:]
        values["packet_manifest_bytes"] = manifest_raw
        attestation = copy.deepcopy(self.attestation)
        attestation["packet_manifest_sha256"] = digest(manifest_raw)
        self._resign(values, attestation)
        with self.assertRaisesRegex(
            PreDistributionAttestationError, "duplicate JSON key"
        ):
            verify_pre_distribution_attestation(**values)

    def test_empty_citation_list_still_binds_to_empty_array_digest(self) -> None:
        values = self._valid()
        packet = copy.deepcopy(self.packet)
        packet["citation_spans"] = []
        self._rebind(
            values,
            packet,
            copy.deepcopy(self.manifest),
            copy.deepcopy(self.attestation),
            citations=True,
        )
        attestation = json.loads(values["attestation_bytes"])
        self.assertEqual(attestation["citation_count"], 0)
        self.assertEqual(attestation["citation_spans_sha256"], digest(b"[]"))
        verify_pre_distribution_attestation(**values)

    def test_long_valid_packet_citations_do_not_expand_attestation(self) -> None:
        values = self._valid()
        sources = copy.deepcopy(self.sources)
        corpus = copy.deepcopy(self.corpus)
        packet = copy.deepcopy(self.packet)
        source = next(
            row
            for row in sources["sources"]
            if row["evidence_id"] == "pub-launch-final"
        )
        offset = len(source["text"])
        source["text"] += "X" * 3000
        packet["source_snapshots"][1]["text"] = source["text"]
        packet["citation_spans"] = [
            {
                "evidence_id": "pub-launch-final",
                "quote": "X" * 1200,
                "start": offset + index,
                "end": offset + index + 1200,
            }
            for index in range(32)
        ]
        corpus["source_pack_digest"] = digest(canonical(sources))
        values["source_pack_bytes"] = encoded(sources)
        values["approved_source_pack_sha256"] = digest(values["source_pack_bytes"])
        values["corpus_bytes"] = encoded(corpus)
        values["approved_corpus_sha256"] = digest(values["corpus_bytes"])
        manifest = copy.deepcopy(self.manifest)
        manifest["corpus_digest"] = digest(canonical(corpus))
        manifest["source_pack_digest"] = digest(canonical(sources))
        attestation = copy.deepcopy(self.attestation)
        attestation["corpus_digest"] = manifest["corpus_digest"]
        attestation["source_pack_digest"] = manifest["source_pack_digest"]
        self._rebind(values, packet, manifest, attestation, citations=True)
        self.assertGreater(len(canonical(packet["citation_spans"])), 32 * 1024)
        self.assertLess(len(values["attestation_bytes"]), 32 * 1024)
        verify_pre_distribution_attestation(**values)

    def test_ordered_citation_digest_uses_utf8_without_unicode_normalization(
        self,
    ) -> None:
        values = self._valid()
        sources = copy.deepcopy(self.sources)
        corpus = copy.deepcopy(self.corpus)
        packet = copy.deepcopy(self.packet)
        source = next(
            row
            for row in sources["sources"]
            if row["evidence_id"] == "pub-launch-final"
        )
        source["text"] += " Café Cafe\u0301."
        corpus["source_pack_digest"] = digest(canonical(sources))
        values["source_pack_bytes"] = encoded(sources)
        values["approved_source_pack_sha256"] = digest(values["source_pack_bytes"])
        values["corpus_bytes"] = encoded(corpus)
        values["approved_corpus_sha256"] = digest(values["corpus_bytes"])
        packet["source_snapshots"][1]["text"] = source["text"]
        precomposed = "Café"
        decomposed = "Cafe\u0301"
        self.assertNotEqual(
            digest(canonical([precomposed])), digest(canonical([decomposed]))
        )
        packet["citation_spans"] = [
            {
                "evidence_id": "pub-launch-final",
                "quote": quote,
                "start": source["text"].index(quote),
                "end": source["text"].index(quote) + len(quote),
            }
            for quote in (precomposed, decomposed)
        ]
        manifest = copy.deepcopy(self.manifest)
        manifest["corpus_digest"] = digest(canonical(corpus))
        manifest["source_pack_digest"] = digest(canonical(sources))
        attestation = copy.deepcopy(self.attestation)
        attestation["corpus_digest"] = manifest["corpus_digest"]
        attestation["source_pack_digest"] = manifest["source_pack_digest"]
        self._rebind(values, packet, manifest, attestation, citations=True)
        self.assertEqual(
            json.loads(values["attestation_bytes"])["citation_spans_sha256"],
            digest(canonical(packet["citation_spans"])),
        )
        verify_pre_distribution_attestation(**values)


if __name__ == "__main__":
    unittest.main()
