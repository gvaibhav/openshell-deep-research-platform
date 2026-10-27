"""CR-0022 isolated cost/export accounting on synthetic observations only."""

from __future__ import annotations

import copy
import hashlib
import json
import unittest
from decimal import Decimal, Inexact, localcontext
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from eval.cost_export import CostExportError, summarize_cost_export

SCHEMA = (
    Path(__file__).resolve().parents[1] / "schemas/cost-export-observations.schema.json"
)


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()


def evidence(name: str) -> dict[str, str]:
    return {
        "ref": f"synthetic-custody://{name}",
        "sha256": hashlib.sha256(name.encode()).hexdigest(),
    }


def fixture() -> tuple[dict[str, Any], dict[str, bytes]]:
    artifact_bytes = (
        b"Synthetic product-native exported report with answer and citations."
    )
    artifact: dict[str, Any] = evidence("export/case-1") | {
        "sha256": hashlib.sha256(artifact_bytes).hexdigest(),
        "byte_count": len(artifact_bytes),
    }
    cell = {
        "case_id": "case-1",
        "status": "completed",
        "run_id": "synthetic-run-1",
        "observed_behavior": "answer",
        "protected_content_disclosed": False,
        "answer_artifact_ref": "synthetic-custody://answer/case-1",
        "raw_answer_sha256": digest("Synthetic answer"),
        "citations_sha256": digest([]),
        "cost": {
            "status": "observed",
            "amount_usd": 0.1,
            "evidence": evidence("usage/case-1"),
        },
        "report_export": {
            "status": "exported",
            "method": "synthetic-product-native-export",
            "attempted_at": "2026-10-26T10:00:00Z",
            "completed_at": "2026-10-26T10:00:02Z",
            "format": "text/plain",
            "artifact": artifact,
            "product_event": evidence("product-event/case-1"),
        },
    }
    bundle = {
        "schema_version": 1,
        "candidate_id": "synthetic-candidate",
        "observer_id": "synthetic-observer",
        "required_cases": [{"case_id": "case-1", "expected_behavior": "answer"}],
        "observations": [cell],
        "corroborations": [],
    }
    bind(bundle)
    return bundle, {artifact["ref"]: artifact_bytes}


def bind(bundle: dict[str, Any]) -> None:
    """Synthetic doubles; these rows are not signed or independent evidence."""
    rows = []
    for cell in bundle["observations"]:
        if cell["status"] != "completed":
            continue
        export = cell["report_export"]
        export_check = {
            "decision": "corroborated",
            "observation_sha256": digest(export),
            "evidence": evidence("independent-export-check/" + cell["case_id"]),
        }
        if export["status"] == "exported":
            export_check["correspondence"] = {
                "run_id": cell["run_id"],
                "artifact_sha256": export["artifact"]["sha256"],
                "product_event_sha256": export["product_event"]["sha256"],
                "raw_answer_sha256": cell["raw_answer_sha256"],
                "citations_sha256": cell["citations_sha256"],
                "inspection_method": "synthetic independent inspection fixture",
                "evidence": evidence("inspection/" + cell["case_id"]),
            }
        rows.append(
            {
                "candidate_id": bundle["candidate_id"],
                "case_id": cell["case_id"],
                "run_id": cell["run_id"],
                "reviewer_id": "synthetic-control-reviewer",
                "cost": {
                    "decision": "corroborated",
                    "observation_sha256": digest(cell["cost"]),
                    "evidence": evidence("independent-cost-check/" + cell["case_id"]),
                    "window_start": "2026-10-26T09:59:00Z",
                    "window_end": "2026-10-26T10:01:00Z",
                    "allocation_basis": "Synthetic case-level provider usage observation",
                },
                "report_export": export_check,
            }
        )
    bundle["corroborations"] = rows


def nonexport(cell: dict[str, Any], status: str) -> None:
    cell["report_export"] = {
        "status": status,
        "reason": "Synthetic recorded outcome",
        "evidence": evidence(status),
    }
    if status == "failed":
        cell["report_export"].update(
            method="synthetic-product-export", attempted_at="2026-10-26T10:00:00Z"
        )
    elif status == "unsupported":
        cell["report_export"]["capability_checked_at"] = "2026-10-26T10:00:00Z"
    elif status == "not_applicable":
        cell["report_export"]["expected_denial_case_id"] = cell["case_id"]


class CostExportTests(unittest.TestCase):
    def test_observed_zero_is_evidenced_numeric_total(self) -> None:
        bundle, artifacts = fixture()
        bundle["observations"][0]["cost"]["amount_usd"] = 0
        bind(bundle)
        result = summarize_cost_export(bundle, export_artifacts=artifacts)
        self.assertEqual(result["observed_subtotal_usd"], Decimal(0))
        self.assertEqual(result["total_cost_usd"], Decimal(0))
        self.assertFalse(result["cost_uncertainty_open"])
        self.assertEqual(result["validation_scope"], "local_synthetic_only")
        self.assertNotIn("ready_for_human_decision", result)
        self.assertNotIn("export_parity", result)

    def test_unavailable_cost_remains_completed_with_uncertainty(self) -> None:
        bundle, artifacts = fixture()
        bundle["observations"][0]["cost"] = {
            "status": "unavailable",
            "reason": "Tenant does not expose case cost",
            "evidence": evidence("tenant-unavailability"),
        }
        bind(bundle)
        result = summarize_cost_export(bundle, export_artifacts=artifacts)
        self.assertEqual(
            (
                result["completed_count"],
                result["observed_cost_count"],
                result["unavailable_cost_count"],
            ),
            (1, 0, 1),
        )
        self.assertIsNone(result["total_cost_usd"])
        self.assertTrue(result["cost_uncertainty_open"])
        self.assertTrue(result["cost_disposition_required"])
        self.assertTrue(result["matrix_complete"])

    def test_decimal_subtotal_and_required_matrix_accounting(self) -> None:
        bundle, artifacts = fixture()
        second = copy.deepcopy(bundle["observations"][0])
        second.update(case_id="case-2", run_id="synthetic-run-2")
        second["cost"]["amount_usd"] = 0.2
        nonexport(second, "not_attempted")
        bundle["observations"].append(second)
        bundle["required_cases"].append(
            {"case_id": "case-2", "expected_behavior": "answer"}
        )
        bind(bundle)
        result = summarize_cost_export(bundle, export_artifacts=artifacts)
        self.assertEqual(result["observed_subtotal_usd"], Decimal("0.3"))
        self.assertEqual(result["total_cost_usd"], Decimal("0.3"))
        self.assertFalse(result["export_outcome_coverage_complete"])
        for status in ("deferred", "failed", "missing"):
            with self.subTest(status=status):
                partial = copy.deepcopy(bundle)
                partial["required_cases"].append(
                    {"case_id": "case-3", "expected_behavior": "answer"}
                )
                if status != "missing":
                    partial["observations"].append(
                        {
                            "case_id": "case-3",
                            "status": status,
                            "reason": "Synthetic pending outcome",
                        }
                    )
                result = summarize_cost_export(partial, export_artifacts=artifacts)
                self.assertEqual(result["observed_subtotal_usd"], Decimal("0.3"))
                self.assertIsNone(result["total_cost_usd"])
                self.assertEqual(result[status + "_count"], 1)
                self.assertEqual(
                    result["required_count"],
                    result["completed_count"]
                    + result["deferred_count"]
                    + result["failed_count"]
                    + result["missing_count"],
                )

    def test_all_missing_is_no_total_or_export_coverage(self) -> None:
        bundle, _ = fixture()
        bundle.update(observations=[], corroborations=[])
        result = summarize_cost_export(bundle, export_artifacts={})
        self.assertEqual(result["missing_count"], 1)
        self.assertIsNone(result["total_cost_usd"])
        self.assertFalse(result["export_outcome_coverage_complete"])

    def test_decimal_context_cannot_round_or_trap_the_local_sum(self) -> None:
        bundle, artifacts = fixture()
        bundle["observations"][0]["cost"]["amount_usd"] = 1e100
        second = copy.deepcopy(bundle["observations"][0])
        second.update(case_id="case-2", run_id="synthetic-run-2")
        second["cost"]["amount_usd"] = 5e-324
        nonexport(second, "not_attempted")
        bundle["required_cases"].append(
            {"case_id": "case-2", "expected_behavior": "answer"}
        )
        bundle["observations"].append(second)
        bind(bundle)
        with localcontext() as context:
            context.prec = 2
            context.Emax = 5
            context.traps[Inexact] = True
            result = summarize_cost_export(bundle, export_artifacts=artifacts)
        expected = Decimal("1" + "0" * 100 + "." + "0" * 323 + "5")
        self.assertEqual(result["total_cost_usd"], expected)

    def test_cost_rejects_unknown_zero_strings_bools_nonfinite_negative(self) -> None:
        for amount in ("unknown", "0", True, float("nan"), float("inf"), -1):
            with self.subTest(amount=str(amount)):
                bundle, artifacts = fixture()
                bundle["observations"][0]["cost"]["amount_usd"] = amount
                with self.assertRaises(CostExportError):
                    summarize_cost_export(bundle, export_artifacts=artifacts)
        bundle, artifacts = fixture()
        bundle["observations"][0]["cost"] = {
            "status": "unavailable",
            "amount_usd": 0,
            "reason": "Unknown",
            "evidence": evidence("unknown"),
        }
        bind(bundle)
        with self.assertRaises(CostExportError):
            summarize_cost_export(bundle, export_artifacts=artifacts)

    def test_cost_requires_evidence_and_bounded_nonblank_unavailable_reason(
        self,
    ) -> None:
        for cost in (
            {"status": "observed", "amount_usd": 0},
            {"status": "unavailable", "reason": "Unknown"},
            {"status": "unavailable", "reason": " ", "evidence": evidence("unknown")},
            {
                "status": "unavailable",
                "reason": "x" * 2049,
                "evidence": evidence("unknown"),
            },
        ):
            with self.subTest(cost=cost["status"]):
                bundle, artifacts = fixture()
                bundle["observations"][0]["cost"] = cost
                bind(bundle)
                with self.assertRaises(CostExportError):
                    summarize_cost_export(bundle, export_artifacts=artifacts)

    def test_abstention_is_export_eligible(self) -> None:
        bundle, artifacts = fixture()
        bundle["required_cases"][0]["expected_behavior"] = "abstain"
        bundle["observations"][0]["observed_behavior"] = "abstained"
        result = summarize_cost_export(bundle, export_artifacts=artifacts)
        self.assertEqual(result["export_eligible_count"], 1)
        self.assertEqual(result["exported_count"], 1)
        self.assertTrue(result["export_outcome_coverage_complete"])

    def test_each_nonexport_outcome_is_separate_and_evidenced(self) -> None:
        for status in ("failed", "unsupported", "unavailable", "not_attempted"):
            with self.subTest(status=status):
                bundle, _ = fixture()
                nonexport(bundle["observations"][0], status)
                bind(bundle)
                result = summarize_cost_export(bundle, export_artifacts={})
                self.assertEqual(result["export_" + status + "_count"], 1)
                self.assertEqual(
                    result["export_outcome_coverage_complete"],
                    status in ("failed", "unsupported"),
                )
                del bundle["observations"][0]["report_export"]["evidence"]
                bind(bundle)
                with self.assertRaises(CostExportError):
                    summarize_cost_export(bundle, export_artifacts={})

    def test_expected_denial_justifies_na_only_without_protected_content(self) -> None:
        bundle, _ = fixture()
        bundle["required_cases"][0]["expected_behavior"] = "deny"
        cell = bundle["observations"][0]
        cell["observed_behavior"] = "denied"
        nonexport(cell, "not_applicable")
        bind(bundle)
        result = summarize_cost_export(bundle, export_artifacts={})
        self.assertEqual(result["not_applicable_count"], 1)
        self.assertEqual(result["export_eligible_count"], 0)
        cell["protected_content_disclosed"] = True
        with self.assertRaises(CostExportError):
            summarize_cost_export(bundle, export_artifacts={})

    def test_unexpected_denial_cannot_use_na_or_imply_quality_success(self) -> None:
        bundle, _ = fixture()
        cell = bundle["observations"][0]
        cell["observed_behavior"] = "denied"
        nonexport(cell, "not_applicable")
        bind(bundle)
        with self.assertRaises(CostExportError):
            summarize_cost_export(bundle, export_artifacts={})
        nonexport(cell, "not_attempted")
        bind(bundle)
        result = summarize_cost_export(bundle, export_artifacts={})
        self.assertEqual(result["behavior_mismatch_count"], 1)
        self.assertFalse(result["export_outcome_coverage_complete"])

    def test_expected_denial_answer_or_export_blocks_local_summary(self) -> None:
        for behavior in ("answer", "denied"):
            with self.subTest(behavior=behavior):
                bundle, artifacts = fixture()
                bundle["required_cases"][0]["expected_behavior"] = "deny"
                bundle["observations"][0]["observed_behavior"] = behavior
                with self.assertRaises(CostExportError):
                    summarize_cost_export(bundle, export_artifacts=artifacts)

    def test_correct_denial_requires_justified_na_for_export_denominator(self) -> None:
        for status in ("failed", "unsupported", "unavailable", "not_attempted"):
            with self.subTest(status=status):
                bundle, _ = fixture()
                bundle["required_cases"][0]["expected_behavior"] = "deny"
                cell = bundle["observations"][0]
                cell["observed_behavior"] = "denied"
                nonexport(cell, status)
                bind(bundle)
                with self.assertRaises(CostExportError):
                    summarize_cost_export(bundle, export_artifacts={})

    def test_submicrosecond_timestamps_are_rejected_without_truncation(self) -> None:
        bundle, artifacts = fixture()
        export = bundle["observations"][0]["report_export"]
        export["attempted_at"] = "2026-10-26T10:00:00.1234569Z"
        export["completed_at"] = "2026-10-26T10:00:00.1234561Z"
        bind(bundle)
        with self.assertRaises(CostExportError):
            summarize_cost_export(bundle, export_artifacts=artifacts)
        validator = Draft202012Validator(json.loads(SCHEMA.read_text()))
        with self.assertRaises(ValidationError):
            validator.validate(bundle)
        export["attempted_at"] = "2026-10-26T10:00:00.123456Z"
        export["completed_at"] = "2026-10-26T10:00:00.123457Z"
        bind(bundle)
        self.assertEqual(
            summarize_cost_export(bundle, export_artifacts=artifacts)["exported_count"],
            1,
        )

    def test_missing_extra_duplicate_and_wrong_run_corroboration_denied(self) -> None:
        for change in ("missing", "duplicate", "wrong_run", "wrong_candidate", "extra"):
            with self.subTest(change=change):
                bundle, artifacts = fixture()
                if change == "missing":
                    bundle["corroborations"] = []
                elif change == "duplicate":
                    bundle["corroborations"] *= 2
                elif change == "extra":
                    extra = copy.deepcopy(bundle["corroborations"][0])
                    extra["case_id"] = "extra-case"
                    bundle["corroborations"].append(extra)
                else:
                    bundle["corroborations"][0][
                        "run_id" if change == "wrong_run" else "candidate_id"
                    ] = "wrong"
                with self.assertRaises(CostExportError):
                    summarize_cost_export(bundle, export_artifacts=artifacts)

    def test_self_review_and_uncorroborated_sections_denied(self) -> None:
        for change in ("reviewer", "cost", "report_export"):
            with self.subTest(change=change):
                bundle, artifacts = fixture()
                row = bundle["corroborations"][0]
                if change == "reviewer":
                    row["reviewer_id"] = bundle["observer_id"]
                else:
                    row[change]["decision"] = "blocked"
                with self.assertRaises(CostExportError):
                    summarize_cost_export(bundle, export_artifacts=artifacts)

    def test_cost_export_mutation_after_corroboration_denied(self) -> None:
        for field in ("cost", "report_export"):
            with self.subTest(field=field):
                bundle, artifacts = fixture()
                if field == "cost":
                    bundle["observations"][0][field]["amount_usd"] = 0
                else:
                    bundle["observations"][0][field]["format"] = "application/pdf"
                with self.assertRaises(CostExportError):
                    summarize_cost_export(bundle, export_artifacts=artifacts)

    def test_empty_wrong_missing_or_unbound_artifact_denied(self) -> None:
        for change in (
            "empty",
            "whitespace",
            "wrong",
            "missing",
            "extra",
            "size",
            "copied_answer",
        ):
            with self.subTest(change=change):
                bundle, artifacts = fixture()
                cell = bundle["observations"][0]
                artifact = cell["report_export"]["artifact"]
                if change in ("empty", "whitespace", "wrong"):
                    artifacts[artifact["ref"]] = {
                        "empty": b"",
                        "whitespace": b" \n",
                        "wrong": b"Wrong report",
                    }[change]
                    if change != "wrong":
                        artifact.update(
                            sha256=hashlib.sha256(
                                artifacts[artifact["ref"]]
                            ).hexdigest(),
                            byte_count=len(artifacts[artifact["ref"]]),
                        )
                elif change == "missing":
                    artifacts.clear()
                elif change == "extra":
                    artifacts["synthetic-custody://extra"] = b"unbound"
                elif change == "size":
                    artifact["byte_count"] += 1
                else:
                    cell["answer_artifact_ref"] = artifact["ref"]
                bind(bundle)
                with self.assertRaises(CostExportError):
                    summarize_cost_export(bundle, export_artifacts=artifacts)

    def test_export_correspondence_requires_same_run_answer_citations_and_event(
        self,
    ) -> None:
        for field in (
            "run_id",
            "artifact_sha256",
            "product_event_sha256",
            "raw_answer_sha256",
            "citations_sha256",
        ):
            with self.subTest(field=field):
                bundle, artifacts = fixture()
                bundle["corroborations"][0]["report_export"]["correspondence"][
                    field
                ] = "wrong" if field == "run_id" else "f" * 64
                with self.assertRaises(CostExportError):
                    summarize_cost_export(bundle, export_artifacts=artifacts)

    def test_export_and_cost_window_time_order_is_checked(self) -> None:
        for change in ("export_order", "invalid_date", "no_offset", "cost_order"):
            with self.subTest(change=change):
                bundle, artifacts = fixture()
                export = bundle["observations"][0]["report_export"]
                if change == "export_order":
                    export["completed_at"] = "2026-10-26T09:00:00Z"
                elif change == "invalid_date":
                    export["completed_at"] = "2026-02-30T10:00:00Z"
                elif change == "no_offset":
                    export["completed_at"] = "2026-10-26T10:00:00"
                bind(bundle)
                if change == "cost_order":
                    bundle["corroborations"][0]["cost"]["window_end"] = (
                        "2026-10-26T09:00:00Z"
                    )
                with self.assertRaises(CostExportError):
                    summarize_cost_export(bundle, export_artifacts=artifacts)

    def test_plan_observation_identity_and_duplicate_runs_are_rejected(self) -> None:
        for change in (
            "empty_plan",
            "duplicate_plan",
            "duplicate_cell",
            "extra_cell",
            "duplicate_run",
            "noncompleted_metric",
        ):
            with self.subTest(change=change):
                bundle, artifacts = fixture()
                if change == "empty_plan":
                    bundle["required_cases"] = []
                elif change == "duplicate_plan":
                    bundle["required_cases"] *= 2
                elif change == "duplicate_cell":
                    bundle["observations"] *= 2
                elif change == "extra_cell":
                    bundle["observations"][0]["case_id"] = "extra-case"
                elif change == "duplicate_run":
                    second = copy.deepcopy(bundle["observations"][0])
                    second["case_id"] = "case-2"
                    bundle["required_cases"].append(
                        {"case_id": "case-2", "expected_behavior": "answer"}
                    )
                    bundle["observations"].append(second)
                else:
                    bundle["observations"] = [
                        {
                            "case_id": "case-1",
                            "status": "deferred",
                            "reason": "Unavailable",
                            "cost": {"status": "observed", "amount_usd": 0},
                        }
                    ]
                bind(bundle)
                with self.assertRaises(CostExportError):
                    summarize_cost_export(bundle, export_artifacts=artifacts)

    def test_missing_export_unknown_fields_and_legacy_versions_deny(self) -> None:
        for change in ("missing_export", "extra_field", "legacy_version"):
            with self.subTest(change=change):
                bundle, artifacts = fixture()
                if change == "missing_export":
                    del bundle["observations"][0]["report_export"]
                elif change == "extra_field":
                    bundle["observations"][0]["cost_usd"] = 0
                else:
                    bundle["schema_version"] = 2
                with self.assertRaises(CostExportError):
                    summarize_cost_export(bundle, export_artifacts=artifacts)

    def test_schema_accepts_supported_branches_and_rejects_unknown_zero(self) -> None:
        validator = Draft202012Validator(
            json.loads(SCHEMA.read_text()), format_checker=FormatChecker()
        )
        bundle, _ = fixture()
        validator.validate(bundle)
        for status in (
            "failed",
            "unsupported",
            "unavailable",
            "not_attempted",
            "not_applicable",
        ):
            nonexport(bundle["observations"][0], status)
            bind(bundle)
            validator.validate(bundle)
        bundle["observations"][0]["cost"] = {
            "status": "unavailable",
            "amount_usd": 0,
            "reason": "Unknown",
            "evidence": evidence("unknown"),
        }
        bind(bundle)
        with self.assertRaises(ValidationError):
            validator.validate(bundle)

    def test_local_bounds_and_input_mutation_are_handled(self) -> None:
        bundle, artifacts = fixture()
        original = copy.deepcopy(bundle)
        summarize_cost_export(bundle, export_artifacts=artifacts)
        self.assertEqual(bundle, original)
        bundle["required_cases"] *= 129
        with self.assertRaises(CostExportError):
            summarize_cost_export(bundle, export_artifacts=artifacts)
        bundle, artifacts = fixture()
        bundle["observer_id"] = "x" * (1024 * 1024)
        with self.assertRaises(CostExportError):
            summarize_cost_export(bundle, export_artifacts=artifacts)


if __name__ == "__main__":
    unittest.main()
