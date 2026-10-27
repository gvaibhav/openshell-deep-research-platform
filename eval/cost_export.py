"""CR-0022 isolated, unused synthetic cost/export binding and coverage helper.

The caller supplies a JSON-compatible Python bundle and bounded retained
artifact bytes. The schema is a local fragment contract, not candidate-run v3.
Money is returned as Decimal in a Python summary; there is no CLI, publication,
signed readiness, quality scoring, distribution, or SEL authority here.

Corroboration rows are assertions. This helper checks their shape, exact cell
and observation bindings, stated correspondence, and supplied artifact bytes.
It cannot authenticate a reviewer, independently approve the required-case
plan, prove a product event, extract a native export, or establish semantic
answer/citation correspondence. Distinct reviewer IDs do not prove distinct
people. Those checks and signed custody remain prerequisites to integration.
Keep candidate-labeled inputs and returned summaries in evaluator custody.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping
from datetime import datetime
from decimal import Context, Decimal, localcontext
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

MAX_BUNDLE_BYTES = 1024 * 1024
MAX_ARTIFACT_BYTES = 1024 * 1024
MAX_TOTAL_ARTIFACT_BYTES = 16 * 1024 * 1024
MAX_CELLS = 128
_SCHEMA = json.loads(
    (Path(__file__).parent / "schemas/cost-export-observations.schema.json").read_text()
)
_VALIDATOR = Draft202012Validator(_SCHEMA, format_checker=FormatChecker())
_BEHAVIORS = {"answer": "answer", "abstain": "abstained", "deny": "denied"}
_TIME_FIELDS = frozenset(
    {
        "attempted_at",
        "completed_at",
        "capability_checked_at",
        "window_start",
        "window_end",
    }
)
_TIME_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})\Z"
)


class CostExportError(ValueError):
    """The supplied synthetic observations cannot support a local summary."""


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeError) as exc:
        raise CostExportError("bundle is not finite JSON-compatible data") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _snapshot(bundle: Any) -> dict[str, Any]:
    raw = _canonical(bundle)
    if len(raw) > MAX_BUNDLE_BYTES:
        raise CostExportError("bundle exceeds its byte bound")
    try:
        detached = json.loads(raw)
    except (ValueError, RecursionError) as exc:
        raise CostExportError("bundle is not valid JSON-compatible data") from exc
    if not _VALIDATOR.is_valid(detached):
        # Schema validation errors contain supplied labels; never echo them.
        raise CostExportError("bundle does not satisfy the local observation schema")
    _validate_times(detached)
    return dict(detached)


def _artifact_snapshot(artifacts: Mapping[str, bytes]) -> dict[str, bytes]:
    if not isinstance(artifacts, Mapping) or len(artifacts) > MAX_CELLS:
        raise CostExportError("artifact collection exceeds its bound")
    result = dict(artifacts)
    total = 0
    for ref, raw in result.items():
        if (
            not isinstance(ref, str)
            or not ref.strip()
            or len(ref) > 2048
            or not isinstance(raw, bytes)
            or len(raw) > MAX_ARTIFACT_BYTES
        ):
            raise CostExportError("artifact reference or bytes are invalid")
        total += len(raw)
    if total > MAX_TOTAL_ARTIFACT_BYTES:
        raise CostExportError("artifact collection exceeds its byte bound")
    return result


def _instant(value: str) -> datetime:
    try:
        if _TIME_RE.fullmatch(value) is None:
            raise ValueError("timestamp syntax")
        moment = datetime.fromisoformat(value)
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ValueError("timestamp offset")
        return moment
    except ValueError as exc:
        raise CostExportError("observation timestamp is invalid") from exc


def _validate_times(value: Any) -> None:
    # date-time format validation is optional in jsonschema installations;
    # validate every time ourselves, including single failed/unsupported events.
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _TIME_FIELDS:
                _instant(item)
            else:
                _validate_times(item)
    elif isinstance(value, list):
        for item in value:
            _validate_times(item)


def _ordered_times(start: str, end: str) -> None:
    if _instant(start) > _instant(end):
        raise CostExportError("observation timestamps are reversed")


def _corroborations(
    bundle: dict[str, Any], completed: dict[str, Any]
) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for row in bundle["corroborations"]:
        case_id = row["case_id"]
        cell = completed.get(case_id)
        if (
            case_id in rows
            or cell is None
            or row["candidate_id"] != bundle["candidate_id"]
            or row["run_id"] != cell["run_id"]
            or row["reviewer_id"] == bundle["observer_id"]
        ):
            raise CostExportError("corroboration cell or reviewer binding is invalid")
        for field in ("cost", "report_export"):
            section = row[field]
            if section["decision"] != "corroborated" or section[
                "observation_sha256"
            ] != _digest(cell[field]):
                raise CostExportError("observation lacks a matching corroboration")
        _ordered_times(row["cost"]["window_start"], row["cost"]["window_end"])
        rows[case_id] = row
    if set(rows) != set(completed):
        raise CostExportError("completed-cell corroboration coverage is incomplete")
    return rows


def _export(
    cell: dict[str, Any],
    row: dict[str, Any],
    expected: str,
    artifacts: dict[str, bytes],
    used_refs: set[str],
) -> str:
    export = cell["report_export"]
    status: str = export["status"]
    if cell["protected_content_disclosed"]:
        raise CostExportError("protected-content disclosure blocks local summary")
    if expected == "deny" and (
        cell["observed_behavior"] != "denied" or status == "exported"
    ):
        raise CostExportError("expected-denial answer or export blocks local summary")
    if expected == "deny" and status != "not_applicable":
        raise CostExportError("correct expected denial requires justified export N/A")
    if status == "not_applicable" and (
        expected != "deny"
        or cell["observed_behavior"] != "denied"
        or export["expected_denial_case_id"] != cell["case_id"]
    ):
        raise CostExportError("export not-applicable lacks a matching expected denial")
    check = row["report_export"]
    if status != "exported":
        if "correspondence" in check:
            raise CostExportError("nonexport outcome has an export correspondence")
        return status
    if "correspondence" not in check:
        raise CostExportError("export lacks a correspondence binding")
    _ordered_times(export["attempted_at"], export["completed_at"])
    artifact = export["artifact"]
    ref = artifact["ref"]
    raw = artifacts.get(ref)
    if (
        raw is None
        or not raw.strip()
        or len(raw) != artifact["byte_count"]
        or hashlib.sha256(raw).hexdigest() != artifact["sha256"]
        or ref == cell["answer_artifact_ref"]
    ):
        raise CostExportError("export artifact bytes or identity do not match")
    correspondence = check["correspondence"]
    expected_bindings = {
        "run_id": cell["run_id"],
        "artifact_sha256": artifact["sha256"],
        "product_event_sha256": export["product_event"]["sha256"],
        "raw_answer_sha256": cell["raw_answer_sha256"],
        "citations_sha256": cell["citations_sha256"],
    }
    if any(correspondence[key] != value for key, value in expected_bindings.items()):
        raise CostExportError("export correspondence does not match the reviewed run")
    used_refs.add(ref)
    return status


def summarize_cost_export(
    bundle: Mapping[str, Any], *, export_artifacts: Mapping[str, bytes]
) -> dict[str, Any]:
    """Return local coverage with Decimal money; authenticate no input claims.

    The bundle must conform to cost-export-observations v1. Its required plan
    is caller-supplied, not approved by this function. Artifact keys are exact
    retained references; unused artifacts are rejected. Completed cells need
    one row each; deferred/failed cells contain no run, cost, or export data.
    Every returned cost is an exact decimal sum of accepted Python numeric
    values' decimal spelling, independent of the caller's Decimal context.
    """
    data = _snapshot(bundle)
    artifacts = _artifact_snapshot(export_artifacts)
    cases: dict[str, str] = {}
    for case in data["required_cases"]:
        if case["case_id"] in cases:
            raise CostExportError("required-case plan contains duplicate cells")
        cases[case["case_id"]] = case["expected_behavior"]
    observations: dict[str, Any] = {}
    completed: dict[str, Any] = {}
    run_ids: set[str] = set()
    counts: Counter[str] = Counter()
    for cell in data["observations"]:
        case_id = cell["case_id"]
        if case_id not in cases or case_id in observations:
            raise CostExportError(
                "observation is duplicate or outside the required plan"
            )
        observations[case_id] = cell
        counts[cell["status"]] += 1
        if cell["status"] == "completed":
            if cell["run_id"] in run_ids:
                raise CostExportError("completed cells reuse a run identity")
            run_ids.add(cell["run_id"])
            completed[case_id] = cell
    rows = _corroborations(data, completed)
    used_refs: set[str] = set()
    amounts: list[Decimal] = []
    mismatches = 0
    for case_id, cell in completed.items():
        cost = cell["cost"]
        counts["cost_" + cost["status"]] += 1
        if cost["status"] == "observed":
            amounts.append(Decimal(str(cost["amount_usd"])))
        status = _export(cell, rows[case_id], cases[case_id], artifacts, used_refs)
        counts["export_" + status] += 1
        mismatches += cell["observed_behavior"] != _BEHAVIORS[cases[case_id]]
    if used_refs != set(artifacts):
        raise CostExportError("artifact collection contains unbound entries")
    # Accepted JSON ints are bounded by Python's parser digit limit, while
    # finite Python floats have at most 324 fractional decimal places. This
    # precision avoids losing even a subnormal contribution beside such ints.
    precision = (
        max(
            (
                len(amount.as_tuple().digits) + max(amount.adjusted(), 0)
                for amount in amounts
            ),
            default=1,
        )
        + 400
    )
    with localcontext(Context(prec=precision)):
        subtotal = sum(amounts, Decimal(0))
    complete = counts["completed"] == len(cases)
    unavailable = counts["cost_unavailable"]
    eligible = counts["completed"] - counts["export_not_applicable"]
    observed_exports = sum(
        counts["export_" + status] for status in ("exported", "failed", "unsupported")
    )
    return {
        "validation_scope": "local_synthetic_only",
        "candidate_id": data["candidate_id"],
        "required_count": len(cases),
        "completed_count": counts["completed"],
        "observed_cost_count": counts["cost_observed"],
        "unavailable_cost_count": unavailable,
        "deferred_count": counts["deferred"],
        "failed_count": counts["failed"],
        "missing_count": len(cases) - len(observations),
        "observed_subtotal_usd": subtotal,
        "total_cost_usd": subtotal if complete and not unavailable else None,
        "matrix_complete": complete,
        "cost_uncertainty_open": unavailable > 0,
        "cost_disposition_required": unavailable > 0,
        "export_eligible_count": eligible,
        "not_applicable_count": counts["export_not_applicable"],
        "exported_count": counts["export_exported"],
        **{
            "export_" + status + "_count": counts["export_" + status]
            for status in ("failed", "unsupported", "unavailable", "not_attempted")
        },
        "export_outcome_coverage_complete": complete and observed_exports == eligible,
        "behavior_mismatch_count": mismatches,
    }
