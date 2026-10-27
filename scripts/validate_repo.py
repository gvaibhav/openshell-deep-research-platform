#!/usr/bin/env python3
"""Check the design contracts and repository links without calling live services."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

import yaml  # type: ignore[import-untyped]
from jsonschema import Draft202012Validator, FormatChecker, SchemaError
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
EXAMPLES = ROOT / "examples"
SCHEMA_DIRS = (CONTRACTS, ROOT / "eval" / "schemas", ROOT / "eval" / "mcp_fixture")
EXAMPLE_SCHEMAS = {
    "job-request.json": "job-request.schema.json",
    "job-policy.json": "job-policy.schema.json",
    "job-policy-typed-transfer.json": "job-policy.schema.json",
    "transfer-grant-created.json": "transfer-grant-created.schema.json",
    "job-access.json": "job-access.schema.json",
    "job-access-shared.json": "job-access.schema.json",
    "job-access-group-revoked.json": "job-access.schema.json",
    "job-access-update.json": "job-access-update.schema.json",
    "job-group-revocation.json": "job-group-revocation.schema.json",
    "stage-public.json": "stage-manifest.schema.json",
    "stage-enterprise.json": "stage-manifest.schema.json",
    "stage-enterprise-synthesis.json": "stage-manifest.schema.json",
    "stage-enterprise-slack-standard.json": "stage-manifest.schema.json",
    "stage-enterprise-correlation.json": "stage-manifest.schema.json",
    "stage-enterprise-synthesis-typed.json": "stage-manifest.schema.json",
    "job-event.json": "job-event.schema.json",
    "evidence.json": "evidence.schema.json",
    "derived-evidence.json": "evidence.schema.json",
    "evidence-view.json": "evidence-view.schema.json",
    "public-evidence.json": "evidence.schema.json",
    "report.json": "report.schema.json",
}
CLASS_RANK = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}
LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
CR_FILE_RE = re.compile(r"^(CR-\d{4})-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
CR_ID_RE = re.compile(r"^\s*(?:-\s*)?\*\*ID:\*\*\s*(CR-\d{4})\s*$", re.MULTILINE)
CR_STATUS_RE = re.compile(r"^\s*(?:-\s*)?\*\*Status:\*\*\s*(.+?)\s*$", re.MULTILINE)
CR_IMPACT_RE = re.compile(r"^\s*(?:-\s*)?\*\*Impact ID:\*\*\s*(\S+)\s*$", re.MULTILINE)
CR_PRIMARY_RE = re.compile(r"^\s*(?:-\s*)?\*\*Primary design:\*\*\s*\[[^\]]+\]\(([^)]+)\)\s*$", re.MULTILINE)
CR_STATUSES = ("Open", "In progress", "Deferred", "Verified", "Withdrawn")
CR_PRIMARY_DESIGN_FILES = frozenset(
    {ROOT / "docs" / "architecture.md", ROOT / "docs" / "okta" / "requirements-and-design.md"}
)
CR_PRIMARY_DESIGN_ROOTS = (ROOT / "docs" / "design", ROOT / "docs" / "decisions")
MERMAID_STARTS = (
    "flowchart ",
    "graph ",
    "sequenceDiagram",
    "stateDiagram",
    "erDiagram",
    "classDiagram",
    "journey",
    "gantt",
    "timeline",
    "mindmap",
    "C4",
)


def read_json(path: Path) -> dict:
    def unique_object(pairs: list[tuple[str, object]]) -> dict:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key {key!r}")
            result[key] = value
        return result

    def finite_only(value: str) -> None:
        raise ValueError(f"non-finite JSON number {value}")

    with path.open(encoding="utf-8") as handle:
        return json.load(handle, object_pairs_hook=unique_object, parse_constant=finite_only)


def instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def human_subject_key(value: object) -> tuple[str, str] | None:
    """Keep dashboard/approval identity as the exact issuer and opaque subject pair."""
    if not isinstance(value, dict) or set(value) != {"iss", "sub"}:
        return None
    issuer, subject = value["iss"], value["sub"]
    if not isinstance(issuer, str) or not isinstance(subject, str) or not issuer or not subject:
        return None
    return issuer, subject


def canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def transfer_creation_matches_policy(
    event: dict, policy: dict, template_digest: str, decisions: dict,
    artifact_bindings: dict[str, str],
) -> bool:
    """Check fixture bindings only; runtime must enforce ledger uniqueness and signatures."""
    grants = policy.get("cross_partition_transfer_grants", [])
    if len(grants) != 1:
        return False
    grant = grants[0]
    partitions = {item["partition_id"]: item for item in policy["source_partitions"]}
    source = partitions.get(grant["source_partition_id"])
    destination = partitions.get(grant["destination_partition_id"])
    if source is None or destination is None:
        return False
    scope = {
        "tenant_id": policy["tenant_id"],
        "job_id": policy["job_id"],
        "policy_version": policy["policy_version"],
        "grant_authorization": {
            key: value for key, value in grant.items()
            if key not in ("approval_ref", "approved_at")
        },
        "source": source,
        "destination": destination,
        "destination_template_sha256": template_digest,
        **artifact_bindings,
    }
    return (
        event["tenant_id"] == policy["tenant_id"]
        and event["job_id"] == policy["job_id"]
        and event["policy_version"] == policy["policy_version"]
        and event["grant_id"] == grant["grant_id"]
        and event["approval_ref"] == grant["approval_ref"] == decisions["approval_ref"]
        and event["approved_at"] == grant["approved_at"]
        and event["destination_template_sha256"] == template_digest
        and all(event[field] == value for field, value in artifact_bindings.items())
        and event["grant_scope_sha256"] == decisions["grant_scope_sha256"] == canonical_sha256(scope)
        and event["approval_decisions_sha256"] == canonical_sha256(decisions)
    )


def same_creation_approval(existing: dict, proposed: dict) -> bool:
    """An idempotent retry returns the old event; it may not append another one."""
    binding_fields = (
        "tenant_id", "job_id", "policy_version", "grant_id", "approval_ref", "approved_at",
        "approval_idempotency_ref", "destination_template_sha256",
        "destination_renderer_artifact_version", "destination_renderer_artifact_sha256",
        "source_extractor_artifact_version", "source_extractor_artifact_sha256",
        "source_verifier_artifact_version", "source_verifier_artifact_sha256",
        "grant_scope_sha256", "approval_decisions_sha256",
    )
    return all(existing[field] == proposed[field] for field in binding_fields)


def stage_can_read_evidence(
    stage: dict, record: dict, producing_attempts: dict[str, dict]
) -> bool:
    """Check example projection shape; live Job API must recheck rights and taint."""
    if stage["stage"] == "public":
        return False
    if stage["stage"] == "enterprise_synthesis":
        return True
    producing_stage = producing_attempts.get(record["producing_attempt_id"])
    if producing_stage is None:
        return False
    if record["connector"] == "public_web":
        return (
            producing_stage["stage"] == "public"
            and record["classification"] == "public"
            and not record["source_dependency_evidence_ids"]
        )
    if record.get("source_partition_id") != stage["source_partition_id"]:
        return False
    if producing_stage["stage"] != "enterprise_retrieval" or producing_stage["source_partition_id"] != record["source_partition_id"]:
        return False
    if stage["retrieval_mode"] == "standard":
        return (
            producing_stage.get("retrieval_mode") == "standard"
            and not record["source_dependency_evidence_ids"]
            and "correlation_derivation" not in record
        )
    return (
        stage["retrieval_mode"] == "correlation_only"
        and record["producing_attempt_id"] == stage["attempt_id"]
        and producing_stage.get("retrieval_mode") == "correlation_only"
        and bool(record["source_dependency_evidence_ids"])
        and "correlation_derivation" in record
    )


def repository_schema_paths() -> list[Path]:
    """Include contract and local evaluation schemas in the repository gate."""
    paths = [path for directory in SCHEMA_DIRS for path in directory.glob("*.schema.json")]
    return sorted(paths)


def load_repository_schemas(errors: list[str]) -> dict[str, dict]:
    """Validate each local JSON Schema before constructing the example registry."""
    schemas: dict[str, dict] = {}
    for path in repository_schema_paths():
        try:
            schema = read_json(path)
            Draft202012Validator.check_schema(schema)
            if schema["$id"] in schemas:
                errors.append(f"Duplicate schema ID: {schema['$id']}")
            schemas[schema["$id"]] = schema
        except (OSError, ValueError, KeyError, TypeError, SchemaError) as exc:
            try:
                shown = path.relative_to(ROOT)
            except ValueError:
                shown = path
            errors.append(f"{shown}: {exc}")
    return schemas


def check_contracts(errors: list[str]) -> tuple[int, int]:
    unregistered_examples = sorted(
        path.name for path in EXAMPLES.glob("*.json") if path.name not in EXAMPLE_SCHEMAS
    )
    for example_name in unregistered_examples:
        errors.append(f"Unregistered JSON example: examples/{example_name}")
    schemas = load_repository_schemas(errors)

    registry = Registry().with_resources(
        (schema_id, Resource.from_contents(schema))
        for schema_id, schema in schemas.items()
    )
    human_subject_validator = Draft202012Validator(
        read_json(CONTRACTS / "human-subject.schema.json"),
        registry=registry,
        format_checker=FormatChecker(),
    )
    examples = {}
    for example_name, schema_name in EXAMPLE_SCHEMAS.items():
        example_path = EXAMPLES / example_name
        schema_path = CONTRACTS / schema_name
        try:
            example = read_json(example_path)
            schema = read_json(schema_path)
            validator = Draft202012Validator(
                schema, registry=registry, format_checker=FormatChecker()
            )
            for problem in validator.iter_errors(example):
                field = ".".join(str(part) for part in problem.absolute_path)
                errors.append(f"{example_path.relative_to(ROOT)}:{field}: {problem.message}")
            examples[example_name] = example
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append(f"{example_path.relative_to(ROOT)}: {exc}")

    if len(examples) == len(EXAMPLE_SCHEMAS):
        request = examples["job-request.json"]
        policy = examples["job-policy.json"]
        typed_transfer_policy = examples["job-policy-typed-transfer.json"]
        transfer_creation = examples["transfer-grant-created.json"]
        access = examples["job-access.json"]
        shared_access = examples["job-access-shared.json"]
        revoked_group_access = examples["job-access-group-revoked.json"]
        access_update = examples["job-access-update.json"]
        group_revocation = examples["job-group-revocation.json"]
        event = examples["job-event.json"]
        evidence = examples["evidence.json"]
        derived_evidence = examples["derived-evidence.json"]
        evidence_view = examples["evidence-view.json"]
        public_evidence = examples["public-evidence.json"]
        report = examples["report.json"]
        public_stage = examples["stage-public.json"]
        enterprise_stage = examples["stage-enterprise.json"]
        synthesis_stage = examples["stage-enterprise-synthesis.json"]
        slack_standard_stage = examples["stage-enterprise-slack-standard.json"]
        correlation_stage = examples["stage-enterprise-correlation.json"]
        typed_synthesis_stage = examples["stage-enterprise-synthesis-typed.json"]

        template_path = EXAMPLES / "approvals" / "slack_commit_sha_v1.json"
        decisions_path = EXAMPLES / "approvals" / "transfer-grant-decisions.json"
        artifact_dir = EXAMPLES / "approvals" / "artifacts"
        try:
            template = read_json(template_path)
            decisions = read_json(decisions_path)
            template_digest = hashlib.sha256(template_path.read_bytes()).hexdigest()
            artifact_bindings = {
                "destination_renderer_artifact_version": "slack-query-renderer-v1",
                "destination_renderer_artifact_sha256": hashlib.sha256(
                    (artifact_dir / "slack-query-renderer-v1.txt").read_bytes()
                ).hexdigest(),
                "source_extractor_artifact_version": "github-commit-extractor-v1",
                "source_extractor_artifact_sha256": hashlib.sha256(
                    (artifact_dir / "github-commit-extractor-v1.txt").read_bytes()
                ).hexdigest(),
                "source_verifier_artifact_version": "github-commit-verifier-v1",
                "source_verifier_artifact_sha256": hashlib.sha256(
                    (artifact_dir / "github-commit-verifier-v1.txt").read_bytes()
                ).hexdigest(),
            }
        except (OSError, ValueError, TypeError) as exc:
            errors.append(f"examples/approvals: {exc}")
            template = {}
            decisions = {}
            template_digest = ""
            artifact_bindings = {}

        if any(
            item["job_id"] != policy["job_id"]
            for item in (event, evidence, derived_evidence, public_evidence, report, public_stage, enterprise_stage, synthesis_stage, slack_standard_stage, correlation_stage, typed_synthesis_stage)
        ):
            errors.append("Example job IDs do not match")
        if request["mode"] != policy["mode"]:
            errors.append("Example request and policy modes do not match")
        if request["visibility_selection"] != access["base_visibility"]:
            errors.append("Initial access policy does not bind the requested visibility")
        for label, acl in (
            ("initial", access),
            ("shared", shared_access),
            ("group-revoked", revoked_group_access),
        ):
            if (acl["job_id"], acl["tenant_id"], acl["owner_subject"]) != (
                policy["job_id"], policy["tenant_id"], policy["user_subject"]
            ):
                errors.append(f"{label} access policy is not bound to the job and tenant")
            subjects = [human_subject_key(grant["subject"]) for grant in acl["reader_subjects"]]
            if None in subjects or len(subjects) != len(set(subjects)):
                errors.append(f"{label} access policy repeats a reader subject")
            for grant in acl["reader_subjects"]:
                if instant(grant["granted_at"]) >= instant(grant["expires_at"]):
                    errors.append(f"{label} reader grant is expired at issue")
        if access["version"] != 1 or access["reader_subjects"] or access["created_at"] != access["updated_at"]:
            errors.append("Initial access policy is not an empty-reader version 1")
        if shared_access["base_visibility"] != access["base_visibility"] or shared_access["version"] != access["version"] + 1:
            errors.append("Reader update changed base visibility or skipped a version")
        if revoked_group_access["base_visibility"] != {"mode": "submitter"} or revoked_group_access["version"] != access["version"] + 1 or revoked_group_access["reader_subjects"] != access["reader_subjects"]:
            errors.append("Group revocation does not only narrow the base audience")
        if not group_revocation["reason"].strip():
            errors.append("Group revocation has no meaningful audit reason")
        if [
            {key: grant[key] for key in ("subject", "actions", "expires_at")}
            for grant in shared_access["reader_subjects"]
        ] != access_update["reader_subjects"]:
            errors.append("Reader update does not match the shared access policy")
        if any(grant["granted_by_subject"] != policy["user_subject"] for grant in shared_access["reader_subjects"]):
            errors.append("Example reader grantor is not the submitter")
        if any(evidence_view[key] != evidence.get(key) for key in evidence_view):
            errors.append("Evidence view changes retained evidence values")
        if {
            "artifact_ref", "access_context_ref", "tool_call_id", "producing_attempt_id", "source_partition_id",
            "source_classification", "dependency_classification_floor", "authorization_sources",
            "source_dependency_evidence_ids", "correlation_derivation",
        } & evidence_view.keys():
            errors.append("Evidence view includes an internal reference")
        if request["sources"] != policy["approved_sources"]:
            errors.append("Example approved sources differ from the request")
        if request["question"] != report["question"]:
            errors.append("Example report question differs from the request")
        if request["public_research_brief"] != policy["public_research_brief"]:
            errors.append("Example public brief differs from approved policy")
        if public_stage["research_brief"] != policy["public_research_brief"]:
            errors.append("Example public stage did not receive approved public brief")
        partition_by_id = {item["partition_id"]: item for item in policy["source_partitions"]}
        if len(partition_by_id) != len(policy["source_partitions"]):
            errors.append("Example policy repeats a source partition ID")
        private_sources = [source for source in policy["approved_sources"] if source["connector"] != "public_web"]
        if sorted(json.dumps(source, sort_keys=True) for source in private_sources) != sorted(
            json.dumps(partition["source"], sort_keys=True) for partition in policy["source_partitions"]
        ):
            errors.append("Example source partitions do not exactly cover approved private sources")
        if policy["cross_partition_transfer_grants"]:
            errors.append("Example default policy unexpectedly allows cross-partition key transfer")
        if typed_transfer_policy["job_id"] != policy["job_id"] or typed_transfer_policy["policy_version"] != policy["policy_version"] + 1:
            errors.append("Typed-transfer example is not a new revision of the same job")
        if typed_transfer_policy["approved_sources"] != policy["approved_sources"] or typed_transfer_policy["source_partitions"] != policy["source_partitions"]:
            errors.append("Typed-transfer example unexpectedly changed source scope or partition briefs")
        if not instant(enterprise_stage["expires_at"]) <= instant(typed_transfer_policy["created_at"]) <= instant(slack_standard_stage["issued_at"]):
            errors.append("Typed-transfer revision was not approved after GitHub retrieval and before Slack starts")
        transfer_grants = typed_transfer_policy["cross_partition_transfer_grants"]
        if len(transfer_grants) != 1:
            errors.append("Typed-transfer example must contain one reviewed grant")
        else:
            grant = transfer_grants[0]
            if (grant["source_partition_id"], grant["destination_partition_id"], grant["allowed_key_types"], grant["destination_tool"], grant["max_destination_calls"]) != (
                "github_repo", "slack_channel", ["commit_sha"], "search_slack", 1
            ):
                errors.append("Typed-transfer example has the wrong source, destination, key type, tool, or call cap")
            if not instant(grant["approved_at"]) <= instant(correlation_stage["issued_at"]) < instant(grant["expires_at"]):
                errors.append("Typed-transfer example stage falls outside grant validity")
            if instant(grant["expires_at"]) > instant(typed_transfer_policy["expires_at"]):
                errors.append("Typed-transfer example grant outlives the job")
            if template and decisions and artifact_bindings:
                expected_arguments = {
                    "channel_id": {"literal": "C0123456789"},
                    "query": {"concat": [{"literal": "commit:"}, {"typed_key": "commit_sha"}]},
                    "limit": {"literal": 10},
                }
                if (
                    template.get("template_id") != grant["destination_query_template_id"]
                    or template.get("upstream_tool") != grant["destination_tool"]
                    or template.get("resource_id") != "C0123456789"
                    or template.get("typed_parameter") not in grant["allowed_key_types"]
                    or template.get("key_validation") != {"pattern": "^[0-9a-f]{40}$", "max_utf8_bytes": 40}
                    or template.get("argument_expression") != expected_arguments
                    or template.get("renderer_artifact_version") != artifact_bindings["destination_renderer_artifact_version"]
                    or template.get("renderer_artifact_sha256") != artifact_bindings["destination_renderer_artifact_sha256"]
                ):
                    errors.append("Pinned Slack template or renderer fixture differs from its reviewed exact argument construction")
                try:
                    source_decision = decisions["source_export"]
                    destination_decision = decisions["destination_acceptance"]
                    if any(
                        item["decision"] != "approved"
                        or item["grant_scope_sha256"] != transfer_creation["grant_scope_sha256"]
                        or not human_subject_validator.is_valid(item.get("actor_subject"))
                        or not item["authority_ref"]
                        or not item["signed_proof_ref"]
                        for item in (source_decision, destination_decision)
                    ):
                        errors.append("Typed-transfer decisions lack A-side or B-side approval provenance")
                    if not max(
                        instant(source_decision["approved_at"]),
                        instant(destination_decision["approved_at"]),
                    ) <= instant(transfer_creation["recorded_at"]) <= instant(typed_transfer_policy["created_at"]):
                        errors.append("Transfer grant creation was not durably recorded after both decisions and before policy issue")
                    if instant(grant["approved_at"]) != max(
                        instant(source_decision["approved_at"]),
                        instant(destination_decision["approved_at"]),
                    ):
                        errors.append("Grant approved_at does not match the completed two-decision set")
                    if not transfer_creation_matches_policy(
                        transfer_creation, typed_transfer_policy, template_digest,
                        decisions, artifact_bindings,
                    ):
                        errors.append("Independent-ledger grant creation does not bind the exact scope, two decisions, template, and adapter artifacts")
                    if not same_creation_approval(transfer_creation, deepcopy(transfer_creation)):
                        errors.append("Identical approval retry was not recognized as the existing creation event")
                    altered_approval = deepcopy(transfer_creation)
                    altered_approval["approval_idempotency_ref"] = "different-approval-transaction"
                    if same_creation_approval(transfer_creation, altered_approval):
                        errors.append("Grant ID accepted reuse by a different approval transaction")
                    changed_scope = deepcopy(typed_transfer_policy)
                    changed_scope["cross_partition_transfer_grants"][0]["max_destination_calls"] = 2
                    if transfer_creation_matches_policy(
                        transfer_creation, changed_scope, template_digest,
                        decisions, artifact_bindings,
                    ):
                        errors.append("Grant creation accepted changed call cap under the old grant ID")
                    changed_renderer = deepcopy(artifact_bindings)
                    changed_renderer["destination_renderer_artifact_sha256"] = "0" * 64
                    if transfer_creation_matches_policy(
                        transfer_creation, typed_transfer_policy, template_digest,
                        decisions, changed_renderer,
                    ):
                        errors.append("Grant creation accepted a changed destination renderer")
                    for adapter_field in (
                        "source_extractor_artifact_sha256", "source_verifier_artifact_sha256"
                    ):
                        changed_adapter = deepcopy(artifact_bindings)
                        changed_adapter[adapter_field] = "0" * 64
                        if transfer_creation_matches_policy(
                            transfer_creation, typed_transfer_policy, template_digest,
                            decisions, changed_adapter,
                        ):
                            errors.append(f"Grant creation accepted a changed {adapter_field}")
                    changed_template = hashlib.sha256(b"different query expression").hexdigest()
                    if transfer_creation_matches_policy(
                        transfer_creation, typed_transfer_policy, changed_template,
                        decisions, artifact_bindings,
                    ):
                        errors.append("Grant creation accepted a changed destination query template")
                except (KeyError, TypeError, ValueError) as exc:
                    errors.append(f"examples/approvals decision set is incomplete: {exc}")
        if correlation_stage["policy_version"] != typed_transfer_policy["policy_version"]:
            errors.append("Typed-transfer stage has the wrong policy revision")
        if slack_standard_stage["policy_version"] != typed_transfer_policy["policy_version"] or typed_synthesis_stage["policy_version"] != typed_transfer_policy["policy_version"]:
            errors.append("Alternative Slack or synthesis stage has the wrong policy revision")
        if slack_standard_stage["retrieval_mode"] != "standard" or "inbound_correlation_key_ids" in slack_standard_stage:
            errors.append("Independent Slack attempt is not standard mode without an inbound A key")
        if correlation_stage["retrieval_mode"] != "correlation_only" or set(correlation_stage["allowed_tools"]) != {"search_by_correlation_key", "read_evidence"}:
            errors.append("Typed destination attempt permits a worker-controlled source tool")
        correlation_partition = partition_by_id.get(correlation_stage["source_partition_id"])
        if correlation_partition is None or correlation_stage["approved_sources"] != [correlation_partition["source"]] or correlation_stage["research_brief"] != correlation_partition["research_brief"]:
            errors.append("Typed-transfer stage did not receive only its destination partition")
        if correlation_partition is None or slack_standard_stage["source_partition_id"] != correlation_stage["source_partition_id"] or slack_standard_stage["approved_sources"] != [correlation_partition["source"]] or slack_standard_stage["research_brief"] != correlation_partition["research_brief"]:
            errors.append("Independent Slack stage did not receive only its partition")
        if slack_standard_stage["context_evidence_ids"] != [public_evidence["evidence_id"]] or "search_by_correlation_key" in slack_standard_stage["allowed_tools"]:
            errors.append("Independent Slack attempt received A-derived context or a correlation tool")
        if correlation_stage["context_evidence_ids"] != [public_evidence["evidence_id"]] or evidence["evidence_id"] in correlation_stage["context_evidence_ids"]:
            errors.append("Typed-transfer stage includes source A private evidence")
        if len(correlation_stage["inbound_correlation_key_ids"]) != 1 or "search_by_correlation_key" not in correlation_stage["allowed_tools"]:
            errors.append("Typed-transfer stage is missing its broker-issued key ID or wrapper")
        if not set(correlation_stage["allowed_tools"]).issubset(typed_transfer_policy["allowed_tools"]):
            errors.append("Typed-transfer stage has a tool outside its policy revision")
        if typed_synthesis_stage["research_brief"] != request["question"] or typed_synthesis_stage["approved_sources"]:
            errors.append("Alternative synthesis lacks full question or has a source connection")
        if typed_synthesis_stage["context_evidence_ids"] != [public_evidence["evidence_id"], evidence["evidence_id"], derived_evidence["evidence_id"]]:
            errors.append("Alternative synthesis lacks curated public, GitHub, and derived Slack evidence")
        if typed_synthesis_stage["model_route"] != typed_transfer_policy["model_route"] or correlation_stage["model_route"] != typed_transfer_policy["model_route"]:
            errors.append("Alternative stages use a different model route from approved policy")
        if CLASS_RANK[correlation_stage["classification"]] < CLASS_RANK[evidence["classification"]]:
            errors.append("Correlation stage class is below inherited GitHub evidence")
        if CLASS_RANK[typed_synthesis_stage["classification"]] < max(
            CLASS_RANK[typed_transfer_policy["classification"]],
            *(CLASS_RANK[item["classification"]] for item in (public_evidence, evidence, derived_evidence)),
        ):
            errors.append("Alternative synthesis stage class is below its declared policy or curated evidence")
        for label, record in (("base", evidence), ("derived", derived_evidence), ("public", public_evidence)):
            floor = max(CLASS_RANK[record["source_classification"]], CLASS_RANK[record["dependency_classification_floor"]])
            if CLASS_RANK[record["classification"]] < floor:
                errors.append(f"{label} evidence classification falls below its recorded floor")
            if record["evidence_id"] in record["source_dependency_evidence_ids"]:
                errors.append(f"{label} evidence depends on itself")
        github_partition = partition_by_id.get("github_repo")
        slack_partition = partition_by_id.get("slack_channel")
        if github_partition is not None:
            github_auth_source = {"partition_id": "github_repo", "source": github_partition["source"]}
            if evidence["source_partition_id"] != "github_repo" or evidence["authorization_sources"] != [github_auth_source]:
                errors.append("Base GitHub evidence lacks its exact primary authorization source")
        if public_evidence["authorization_sources"] or public_evidence["source_dependency_evidence_ids"]:
            errors.append("Public evidence inherits a private source dependency")
        if evidence["source_dependency_evidence_ids"] or evidence.get("correlation_derivation") or public_evidence.get("correlation_derivation"):
            errors.append("Independent evidence unexpectedly carries correlation lineage")
        if slack_partition is not None and github_partition is not None:
            slack_auth_source = {"partition_id": "slack_channel", "source": slack_partition["source"]}
            expected_closure = [slack_auth_source, *evidence["authorization_sources"]]
            if derived_evidence["source_partition_id"] != "slack_channel" or derived_evidence["connector"] != "slack":
                errors.append("Derived evidence is not bound to the destination partition")
            if derived_evidence["authorization_sources"] != expected_closure:
                errors.append("Derived evidence omits or changes its A-plus-B source/resource closure")
        expected_dependencies = [evidence["evidence_id"], *evidence["source_dependency_evidence_ids"]]
        if derived_evidence["source_dependency_evidence_ids"] != expected_dependencies:
            errors.append("Derived evidence omits its transitive origin evidence IDs")
        if derived_evidence["dependency_classification_floor"] != evidence["classification"]:
            errors.append("Derived evidence does not inherit its origin classification floor")
        for record, producing_stage in (
            (public_evidence, public_stage),
            (evidence, enterprise_stage),
            (derived_evidence, correlation_stage),
        ):
            if record["producing_attempt_id"] != producing_stage["attempt_id"]:
                errors.append("Example evidence does not bind its trusted producing attempt")
        derivation = derived_evidence["correlation_derivation"]
        if derivation["kind"] != "direct_correlation_result" or derivation["correlation_key_ids"] != correlation_stage["inbound_correlation_key_ids"]:
            errors.append("Derived evidence does not bind the destination key ID")
        if len(transfer_grants) == 1 and derivation["transfer_grant_ids"] != [transfer_grants[0]["grant_id"]]:
            errors.append("Derived evidence does not bind its reviewed transfer grant")
        if not instant(correlation_stage["issued_at"]) <= instant(derived_evidence["retrieved_at"]) < instant(correlation_stage["expires_at"]):
            errors.append("Derived evidence falls outside its destination attempt")
        if CLASS_RANK[correlation_stage["classification"]] < CLASS_RANK[derived_evidence["classification"]]:
            errors.append("Derived response exceeds its destination stage class")
        commit_ref = re.search(r"/blob/([0-9a-f]{40})/", evidence["resource_uri"])
        if commit_ref is None or commit_ref.group(1) not in derived_evidence["excerpt"]:
            errors.append("Derived example does not reference the GitHub immutable commit metadata")
        selected_partition = partition_by_id.get(enterprise_stage["source_partition_id"])
        if selected_partition is None or enterprise_stage["research_brief"] != selected_partition["research_brief"]:
            errors.append("Example enterprise retrieval did not receive its approved partition brief")
        if synthesis_stage["research_brief"] != request["question"]:
            errors.append("Example enterprise synthesis did not receive the full private question")
        if event.get("evidence_id") != evidence["evidence_id"]:
            errors.append("Example event evidence ID does not resolve")
        known_evidence = {evidence["evidence_id"], public_evidence["evidence_id"], derived_evidence["evidence_id"]}
        if any(
            cited_id not in known_evidence
            for finding in report["findings"]
            for cited_id in finding["evidence_ids"]
        ):
            errors.append("Example report cites unknown evidence")
        if public_evidence["classification"] != "public" or public_evidence["connector"] != "public_web":
            errors.append("Public stage context is not public evidence")
        for record, fixture in (
            (evidence, EXAMPLES / "artifacts" / "private-evidence.txt"),
            (public_evidence, EXAMPLES / "artifacts" / "public-evidence.txt"),
            (derived_evidence, EXAMPLES / "artifacts" / "derived-evidence.txt"),
        ):
            snapshot = fixture.read_bytes()
            if hashlib.sha256(snapshot).hexdigest() != record["content_sha256"]:
                errors.append(f"{fixture.relative_to(ROOT)} does not match evidence digest")
            if record.get("excerpt") and record["excerpt"] not in snapshot.decode("utf-8"):
                errors.append(f"{fixture.relative_to(ROOT)} does not contain the evidence excerpt")
        if enterprise_stage["context_evidence_ids"] != [public_evidence["evidence_id"]]:
            errors.append("Enterprise retrieval context does not resolve to public evidence")
        if synthesis_stage["context_evidence_ids"] != [public_evidence["evidence_id"], evidence["evidence_id"]]:
            errors.append("Enterprise synthesis context does not resolve to captured evidence")
        if public_stage["approved_sources"] != [source for source in policy["approved_sources"] if source["connector"] == "public_web"]:
            errors.append("Public stage source projection differs from policy")
        if selected_partition is not None and enterprise_stage["approved_sources"] != [selected_partition["source"]]:
            errors.append("Enterprise retrieval source projection differs from its partition")
        if synthesis_stage["approved_sources"]:
            errors.append("Enterprise synthesis stage has a source connection")
        for stage, stage_policy in (
            (public_stage, policy),
            (enterprise_stage, policy),
            (synthesis_stage, policy),
            (slack_standard_stage, typed_transfer_policy),
            (correlation_stage, typed_transfer_policy),
            (typed_synthesis_stage, typed_transfer_policy),
        ):
            if stage["policy_version"] != stage_policy["policy_version"]:
                errors.append(f"{stage['stage']} stage has the wrong policy version")
            if not set(stage["allowed_tools"]).issubset(stage_policy["allowed_tools"]):
                errors.append(f"{stage['stage']} stage has a tool outside the job policy")
            if instant(stage["issued_at"]) >= instant(stage["expires_at"]):
                errors.append(f"{stage['stage']} stage has an empty or reversed lifetime")
            if instant(stage["expires_at"]) > instant(stage_policy["expires_at"]):
                errors.append(f"{stage['stage']} stage outlives the job")
            for key, value in stage["limits"].items():
                if value > stage_policy["limits"][key]:
                    errors.append(f"{stage['stage']} stage exceeds job {key}")
        default_branch = (public_stage, enterprise_stage, synthesis_stage)
        typed_branch = (public_stage, enterprise_stage, slack_standard_stage, correlation_stage, typed_synthesis_stage)
        for branch_label, branch in (("default", default_branch), ("typed", typed_branch)):
            for earlier, later in zip(branch, branch[1:]):
                if instant(earlier["expires_at"]) > instant(later["issued_at"]):
                    errors.append(f"{branch_label} example stages overlap in time")
            generations = [stage["fencing_generation"] for stage in branch]
            if generations != sorted(set(generations)):
                errors.append(f"{branch_label} stage fencing generations do not advance uniquely")
        if instant(typed_synthesis_stage["issued_at"]) <= instant(derived_evidence["retrieved_at"]):
            errors.append("Alternative synthesis begins before derived evidence capture finishes")
        for stage, record in ((public_stage, public_evidence), (enterprise_stage, evidence)):
            retrieved = instant(record["retrieved_at"])
            if not instant(stage["issued_at"]) <= retrieved < instant(stage["expires_at"]):
                errors.append(f"{stage['stage']} evidence falls outside its stage lifetime")
        if not instant(evidence["retrieved_at"]) <= instant(event["at"]) <= instant(report["generated_at"]):
            errors.append("Example event/report timeline is inconsistent")
        if not instant(synthesis_stage["issued_at"]) <= instant(report["generated_at"]) < instant(synthesis_stage["expires_at"]):
            errors.append("Example report was not generated in synthesis stage")
        all_stages = (*default_branch, slack_standard_stage, correlation_stage, typed_synthesis_stage)
        for identity in ("manifest_id", "attempt_id", "sandbox_id"):
            if len({stage[identity] for stage in all_stages}) != len(all_stages):
                errors.append(f"Example stages reuse a {identity} across alternative branches")
        for branch_label, branch_policy, branch in (
            ("default", policy, default_branch),
            ("typed", typed_transfer_policy, typed_branch),
        ):
            for key, limit in branch_policy["limits"].items():
                if sum(stage["limits"].get(key, 0) for stage in branch) > limit:
                    errors.append(f"{branch_label} stage budgets exceed job {key}")
        records_by_id = {
            record["evidence_id"]: record
            for record in (public_evidence, evidence, derived_evidence)
        }
        attempts_by_id = {stage["attempt_id"]: stage for stage in all_stages}
        for stage in all_stages:
            for evidence_id in stage.get("context_evidence_ids", []):
                candidate_record = records_by_id.get(evidence_id)
                if candidate_record is None or not stage_can_read_evidence(stage, candidate_record, attempts_by_id):
                    errors.append("Example stage projects evidence outside its retrieval mode and trusted attempt")
        if stage_can_read_evidence(slack_standard_stage, derived_evidence, attempts_by_id):
            errors.append("Contract guard failed: standard Slack attempt read A-derived Slack evidence")
        replay_standard_stage = deepcopy(slack_standard_stage)
        replay_standard_stage["context_evidence_ids"].append(derived_evidence["evidence_id"])
        if all(
            stage_can_read_evidence(replay_standard_stage, records_by_id[evidence_id], attempts_by_id)
            for evidence_id in replay_standard_stage["context_evidence_ids"]
        ):
            errors.append("Contract guard failed: standard Slack manifest projected known A-derived Slack ID")
        if not stage_can_read_evidence(correlation_stage, derived_evidence, attempts_by_id):
            errors.append("Contract guard failed: correlation attempt cannot read its own derived evidence")
        independent_slack_probe = deepcopy(derived_evidence)
        independent_slack_probe["producing_attempt_id"] = slack_standard_stage["attempt_id"]
        independent_slack_probe["source_dependency_evidence_ids"] = []
        independent_slack_probe["dependency_classification_floor"] = "public"
        independent_slack_probe["authorization_sources"] = [
            item for item in derived_evidence["authorization_sources"] if item["partition_id"] == "slack_channel"
        ]
        independent_slack_probe.pop("correlation_derivation")
        if stage_can_read_evidence(correlation_stage, independent_slack_probe, attempts_by_id):
            errors.append("Contract guard failed: tainted Slack worker read earlier independent Slack evidence")
        if instant(policy["created_at"]) >= instant(policy["expires_at"]):
            errors.append("Example policy expires before its creation")
        if instant(request["time_range"]["start"]) >= instant(request["time_range"]["end"]):
            errors.append("Example time range is empty or reversed")
        for data, field in ((request, "sources"), (policy, "approved_sources")):
            public = any(source["connector"] == "public_web" for source in data[field])
            private = any(source["connector"] != "public_web" for source in data[field])
            mode = data["mode"]
            if (mode == "public" and private) or (mode == "enterprise" and public) or (mode == "combined" and not (public and private)):
                errors.append(f"Example {field} conflicts with {mode} mode")

        guard_cases: list[tuple[str, dict, str]] = []
        unauthorized_request = deepcopy(request)
        unauthorized_request["tenant_id"] = "another-tenant"
        guard_cases.append(("job-request.schema.json", unauthorized_request, "browser-supplied tenant"))
        unauthorized_owner = deepcopy(request)
        unauthorized_owner["owner_subject"] = "forged-owner"
        guard_cases.append(("job-request.schema.json", unauthorized_owner, "browser-supplied owner"))
        unauthorized_acl = deepcopy(request)
        unauthorized_acl["reader_subjects"] = []
        guard_cases.append(("job-request.schema.json", unauthorized_acl, "browser-supplied reader ACL"))
        bare_policy_subject = deepcopy(policy)
        bare_policy_subject["user_subject"] = policy["user_subject"]["sub"]
        guard_cases.append(("job-policy.schema.json", bare_policy_subject, "bare submitter sub without issuer"))
        bare_access_owner = deepcopy(access)
        bare_access_owner["owner_subject"] = access["owner_subject"]["sub"]
        guard_cases.append(("job-access.schema.json", bare_access_owner, "bare access owner sub without issuer"))
        if human_subject_key(policy["user_subject"]) == human_subject_key({
            "iss": "https://another-issuer.example.invalid/oauth2/dashboard",
            "sub": policy["user_subject"]["sub"],
        }):
            errors.append("Contract guard failed: equal sub values from different issuers collided")
        missing_group_id = deepcopy(request)
        missing_group_id["visibility_selection"] = {"mode": "okta_group"}
        guard_cases.append(("job-request.schema.json", missing_group_id, "group choice without stable group ID"))
        group_with_owner = deepcopy(request)
        group_with_owner["visibility_selection"]["owner_subject"] = "forged-owner"
        guard_cases.append(("job-request.schema.json", group_with_owner, "group choice with forged owner"))
        no_public_brief = deepcopy(request)
        del no_public_brief["public_research_brief"]
        guard_cases.append(("job-request.schema.json", no_public_brief, "combined request without public brief"))
        no_approval = deepcopy(policy)
        del no_approval["public_brief_approval_ref"]
        guard_cases.append(("job-policy.schema.json", no_approval, "combined policy without brief approval"))
        no_partition_plan = deepcopy(policy)
        del no_partition_plan["source_partitions"]
        guard_cases.append(("job-policy.schema.json", no_partition_plan, "private policy without source partitions"))
        no_transfer_default = deepcopy(policy)
        del no_transfer_default["cross_partition_transfer_grants"]
        guard_cases.append(("job-policy.schema.json", no_transfer_default, "private policy without explicit transfer default"))
        public_partition = deepcopy(policy)
        public_partition["source_partitions"][0]["source"] = policy["approved_sources"][0]
        guard_cases.append(("job-policy.schema.json", public_partition, "public source in a private partition"))
        unreviewed_shared_domain = deepcopy(policy)
        unreviewed_shared_domain["source_partitions"][0]["source"]["resource_ids"].append("example-org/another-repo")
        guard_cases.append(("job-policy.schema.json", unreviewed_shared_domain, "multi-resource partition without shared-domain approval"))
        reviewed_transfer = deepcopy(policy)
        reviewed_transfer["cross_partition_transfer_grants"] = [{
            "grant_id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
            "source_partition_id": "slack_channel",
            "destination_partition_id": "github_repo",
            "allowed_key_types": ["incident_id"],
            "destination_tool": "search_github",
            "destination_query_template_id": "github_incident_id_v1",
            "max_keys": 2,
            "max_value_bytes": 64,
            "max_total_bytes": 128,
            "max_destination_calls": 2,
            "approval_ref": "decisions-slack-export-and-github-template-1",
            "approved_at": "2026-10-23T12:00:00Z",
            "expires_at": "2026-10-23T13:00:00Z",
        }]
        policy_validator = Draft202012Validator(
            read_json(CONTRACTS / "job-policy.schema.json"), registry=registry, format_checker=FormatChecker()
        )
        if not policy_validator.is_valid(reviewed_transfer):
            errors.append("Contract guard failed: rejected a reviewed typed transfer grant")
        unreviewed_transfer = deepcopy(reviewed_transfer)
        del unreviewed_transfer["cross_partition_transfer_grants"][0]["approval_ref"]
        guard_cases.append(("job-policy.schema.json", unreviewed_transfer, "cross-partition grant without approval provenance"))
        untyped_transfer = deepcopy(reviewed_transfer)
        untyped_transfer["cross_partition_transfer_grants"][0]["allowed_key_types"] = ["arbitrary_text"]
        guard_cases.append(("job-policy.schema.json", untyped_transfer, "cross-partition grant for arbitrary text"))
        unbounded_transfer_calls = deepcopy(reviewed_transfer)
        del unbounded_transfer_calls["cross_partition_transfer_grants"][0]["max_destination_calls"]
        guard_cases.append(("job-policy.schema.json", unbounded_transfer_calls, "typed transfer without destination call cap"))
        creation_without_scope = deepcopy(transfer_creation)
        del creation_without_scope["grant_scope_sha256"]
        guard_cases.append(("transfer-grant-created.schema.json", creation_without_scope, "grant creation without immutable scope digest"))
        creation_without_adapter = deepcopy(transfer_creation)
        del creation_without_adapter["source_verifier_artifact_sha256"]
        guard_cases.append(("transfer-grant-created.schema.json", creation_without_adapter, "grant creation without source verifier artifact digest"))
        public_with_private_source = deepcopy(public_stage)
        public_with_private_source["approved_sources"].append(policy["approved_sources"][1])
        guard_cases.append(("stage-manifest.schema.json", public_with_private_source, "public stage with private source"))
        private_with_public_source = deepcopy(enterprise_stage)
        private_with_public_source["approved_sources"].append(policy["approved_sources"][0])
        guard_cases.append(("stage-manifest.schema.json", private_with_public_source, "enterprise stage with public source"))
        private_with_second_source = deepcopy(enterprise_stage)
        private_with_second_source["approved_sources"].append(policy["approved_sources"][2])
        guard_cases.append(("stage-manifest.schema.json", private_with_second_source, "retrieval stage with two private sources"))
        private_without_partition = deepcopy(enterprise_stage)
        del private_without_partition["source_partition_id"]
        guard_cases.append(("stage-manifest.schema.json", private_without_partition, "retrieval stage without partition binding"))
        synthesis_with_source = deepcopy(synthesis_stage)
        synthesis_with_source["approved_sources"].append(policy["approved_sources"][1])
        guard_cases.append(("stage-manifest.schema.json", synthesis_with_source, "synthesis stage with a source connection"))
        synthesis_with_source_tool = deepcopy(synthesis_stage)
        synthesis_with_source_tool["allowed_tools"].append("search_github")
        guard_cases.append(("stage-manifest.schema.json", synthesis_with_source_tool, "synthesis stage with a source tool"))
        correlation_with_raw_value = deepcopy(correlation_stage)
        correlation_with_raw_value["inbound_correlation_key_values"] = ["0123456789abcdef0123456789abcdef01234567"]
        guard_cases.append(("stage-manifest.schema.json", correlation_with_raw_value, "destination stage carrying a raw correlation value"))
        correlation_without_wrapper = deepcopy(correlation_stage)
        correlation_without_wrapper["allowed_tools"].remove("search_by_correlation_key")
        guard_cases.append(("stage-manifest.schema.json", correlation_without_wrapper, "destination stage with key ID but no correlation wrapper"))
        correlation_without_key = deepcopy(correlation_stage)
        del correlation_without_key["inbound_correlation_key_ids"]
        guard_cases.append(("stage-manifest.schema.json", correlation_without_key, "destination stage with correlation wrapper but no key ID"))
        correlation_with_41_keys = deepcopy(correlation_stage)
        correlation_with_41_keys["inbound_correlation_key_ids"] = [
            f"00000000-0000-4000-8000-{number:012x}" for number in range(1, 42)
        ]
        guard_cases.append(("stage-manifest.schema.json", correlation_with_41_keys, "destination stage with 41 inbound key IDs beyond evidence derivation capacity"))
        for tool in ("search_slack", "read_slack_thread", "read_github_file", "list_log_entries"):
            correlation_with_freeform_tool = deepcopy(correlation_stage)
            correlation_with_freeform_tool["allowed_tools"].append(tool)
            guard_cases.append(("stage-manifest.schema.json", correlation_with_freeform_tool, f"correlation-only stage with worker-controlled {tool}"))
        standard_with_wrapper = deepcopy(slack_standard_stage)
        standard_with_wrapper["allowed_tools"].append("search_by_correlation_key")
        guard_cases.append(("stage-manifest.schema.json", standard_with_wrapper, "standard stage with correlation wrapper"))
        standard_with_key = deepcopy(slack_standard_stage)
        standard_with_key["inbound_correlation_key_ids"] = correlation_stage["inbound_correlation_key_ids"]
        guard_cases.append(("stage-manifest.schema.json", standard_with_key, "standard stage with inbound A key"))
        correlation_without_mode = deepcopy(correlation_stage)
        del correlation_without_mode["retrieval_mode"]
        guard_cases.append(("stage-manifest.schema.json", correlation_without_mode, "correlation stage without retrieval mode"))
        public_with_correlation_key = deepcopy(public_stage)
        public_with_correlation_key["inbound_correlation_key_ids"] = correlation_stage["inbound_correlation_key_ids"]
        guard_cases.append(("stage-manifest.schema.json", public_with_correlation_key, "public stage carrying private correlation key IDs"))
        public_with_private_tool = deepcopy(public_stage)
        public_with_private_tool["allowed_tools"].append("search_slack")
        guard_cases.append(("stage-manifest.schema.json", public_with_private_tool, "public stage with private tool"))
        private_with_public_tool = deepcopy(enterprise_stage)
        private_with_public_tool["allowed_tools"].append("search_public_web")
        guard_cases.append(("stage-manifest.schema.json", private_with_public_tool, "enterprise stage with public tool"))
        evidence_without_call = deepcopy(evidence)
        del evidence_without_call["tool_call_id"]
        guard_cases.append(("evidence.schema.json", evidence_without_call, "evidence without tool call ID"))
        evidence_without_attempt = deepcopy(evidence)
        del evidence_without_attempt["producing_attempt_id"]
        guard_cases.append(("evidence.schema.json", evidence_without_attempt, "evidence without trusted producing attempt"))
        evidence_without_closure = deepcopy(evidence)
        del evidence_without_closure["authorization_sources"]
        guard_cases.append(("evidence.schema.json", evidence_without_closure, "private evidence without source/resource authorization closure"))
        derived_without_origin = deepcopy(derived_evidence)
        del derived_without_origin["source_dependency_evidence_ids"]
        guard_cases.append(("evidence.schema.json", derived_without_origin, "derived evidence without required dependency IDs"))
        derived_without_derivation = deepcopy(derived_evidence)
        del derived_without_derivation["correlation_derivation"]
        guard_cases.append(("evidence.schema.json", derived_without_derivation, "derived evidence without correlation provenance"))
        derived_without_sources = deepcopy(derived_evidence)
        derived_without_sources["authorization_sources"] = []
        guard_cases.append(("evidence.schema.json", derived_without_sources, "derived evidence without primary and origin source closure"))
        public_with_dependency = deepcopy(public_evidence)
        public_with_dependency["source_dependency_evidence_ids"] = [evidence["evidence_id"]]
        guard_cases.append(("evidence.schema.json", public_with_dependency, "public evidence with private dependency"))
        evidence_view_with_artifact = deepcopy(evidence_view)
        evidence_view_with_artifact["artifact_ref"] = evidence["artifact_ref"]
        guard_cases.append(("evidence-view.schema.json", evidence_view_with_artifact, "browser evidence with artifact reference"))
        evidence_view_with_context = deepcopy(evidence_view)
        evidence_view_with_context["access_context_ref"] = evidence["access_context_ref"]
        guard_cases.append(("evidence-view.schema.json", evidence_view_with_context, "browser evidence with access context"))
        evidence_view_with_lineage = deepcopy(evidence_view)
        evidence_view_with_lineage["source_dependency_evidence_ids"] = derived_evidence["source_dependency_evidence_ids"]
        guard_cases.append(("evidence-view.schema.json", evidence_view_with_lineage, "browser evidence with internal lineage"))
        evidence_view_with_attempt = deepcopy(evidence_view)
        evidence_view_with_attempt["producing_attempt_id"] = evidence["producing_attempt_id"]
        guard_cases.append(("evidence-view.schema.json", evidence_view_with_attempt, "browser evidence with internal attempt ID"))
        arbitrary_event_message = deepcopy(event)
        arbitrary_event_message["message"] = "A private repository change exposed a secret."
        guard_cases.append(("job-event.schema.json", arbitrary_event_message, "worker-generated event prose"))
        valid_status_event = deepcopy(event)
        valid_status_event["type"] = "status"
        valid_status_event["status"] = "running"
        valid_status_event["message"] = "Research in progress."
        del valid_status_event["evidence_id"]
        event_validator = Draft202012Validator(
            read_json(CONTRACTS / "job-event.schema.json"),
            registry=registry,
            format_checker=FormatChecker(),
        )
        if not event_validator.is_valid(valid_status_event):
            errors.append("Contract guard failed: rejected a valid running status event")
        valid_warning_event = deepcopy(event)
        valid_warning_event["type"] = "warning"
        valid_warning_event["issue_code"] = "SOURCE_UNAVAILABLE"
        valid_warning_event["message"] = "A research source is unavailable."
        del valid_warning_event["evidence_id"]
        if not event_validator.is_valid(valid_warning_event):
            errors.append("Contract guard failed: rejected a valid sanitized source warning")
        valid_error_event = deepcopy(valid_warning_event)
        valid_error_event["type"] = "error"
        valid_error_event["stage"] = "synthesis"
        valid_error_event["issue_code"] = "MODEL_UNAVAILABLE"
        valid_error_event["message"] = "Research model is unavailable."
        if not event_validator.is_valid(valid_error_event):
            errors.append("Contract guard failed: rejected a valid sanitized model error")
        evidence_event_without_id = deepcopy(event)
        del evidence_event_without_id["evidence_id"]
        guard_cases.append(("job-event.schema.json", evidence_event_without_id, "evidence event without an authorized evidence ID"))
        evidence_with_wrong_stage = deepcopy(event)
        evidence_with_wrong_stage["stage"] = "synthesis"
        guard_cases.append(("job-event.schema.json", evidence_with_wrong_stage, "evidence event outside retrieval"))
        evidence_with_source_stage = deepcopy(event)
        evidence_with_source_stage["stage"] = "github_retrieval"
        guard_cases.append(("job-event.schema.json", evidence_with_source_stage, "event stage leaking a source identity"))
        progress_with_evidence_id = deepcopy(event)
        progress_with_evidence_id["type"] = "progress"
        progress_with_evidence_id["message"] = "Research in progress."
        guard_cases.append(("job-event.schema.json", progress_with_evidence_id, "progress event leaking an evidence ID"))
        progress_without_stage = deepcopy(progress_with_evidence_id)
        del progress_without_stage["evidence_id"]
        del progress_without_stage["stage"]
        guard_cases.append(("job-event.schema.json", progress_without_stage, "progress event without a coarse phase"))
        progress_with_issue_code = deepcopy(progress_without_stage)
        progress_with_issue_code["stage"] = "retrieval"
        progress_with_issue_code["issue_code"] = "SOURCE_UNAVAILABLE"
        guard_cases.append(("job-event.schema.json", progress_with_issue_code, "progress event carrying a failure code"))
        evidence_with_wrong_template = deepcopy(event)
        evidence_with_wrong_template["message"] = "Research in progress."
        guard_cases.append(("job-event.schema.json", evidence_with_wrong_template, "evidence event with an unrelated message"))
        warning_without_issue_code = deepcopy(valid_warning_event)
        del warning_without_issue_code["issue_code"]
        guard_cases.append(("job-event.schema.json", warning_without_issue_code, "warning without a typed issue code"))
        warning_with_source_name = deepcopy(valid_warning_event)
        warning_with_source_name["issue_code"] = "GITHUB_REPOSITORY_UNAVAILABLE"
        guard_cases.append(("job-event.schema.json", warning_with_source_name, "source-identifying issue code"))
        warning_with_wrong_message = deepcopy(valid_warning_event)
        warning_with_wrong_message["message"] = "Research model is unavailable."
        guard_cases.append(("job-event.schema.json", warning_with_wrong_message, "source issue with model message"))
        error_with_wrong_message = deepcopy(valid_error_event)
        error_with_wrong_message["message"] = "A research source is unavailable."
        guard_cases.append(("job-event.schema.json", error_with_wrong_message, "model error with source message"))
        status_without_status = deepcopy(event)
        status_without_status["type"] = "status"
        status_without_status["message"] = "Research in progress."
        del status_without_status["evidence_id"]
        guard_cases.append(("job-event.schema.json", status_without_status, "status event without a status"))
        running_without_stage = deepcopy(valid_status_event)
        del running_without_stage["stage"]
        guard_cases.append(("job-event.schema.json", running_without_stage, "running status without a coarse phase"))
        status_with_wrong_message = deepcopy(status_without_status)
        status_with_wrong_message["status"] = "completed"
        guard_cases.append(("job-event.schema.json", status_with_wrong_message, "completed status with progress template"))
        completed_with_stage = deepcopy(valid_status_event)
        completed_with_stage["status"] = "completed"
        completed_with_stage["message"] = "Job completed."
        guard_cases.append(("job-event.schema.json", completed_with_stage, "terminal status carrying a stale phase"))
        progress_with_terminal_status = deepcopy(progress_with_evidence_id)
        del progress_with_terminal_status["evidence_id"]
        progress_with_terminal_status["status"] = "completed"
        guard_cases.append(("job-event.schema.json", progress_with_terminal_status, "progress event carrying a terminal status"))
        update_with_base = deepcopy(access_update)
        update_with_base["base_visibility"] = {"mode": "okta_group", "okta_group_id": "another-group"}
        guard_cases.append(("job-access-update.schema.json", update_with_base, "reader update changing base visibility"))
        update_with_tenant = deepcopy(access_update)
        update_with_tenant["tenant_id"] = "another-tenant"
        guard_cases.append(("job-access-update.schema.json", update_with_tenant, "reader update changing tenant"))
        update_with_audit_field = deepcopy(access_update)
        update_with_audit_field["reader_subjects"][0]["grant_id"] = "77777777-7777-4777-8777-777777777777"
        guard_cases.append(("job-access-update.schema.json", update_with_audit_field, "browser-assigned grant ID"))
        update_without_expiry = deepcopy(access_update)
        del update_without_expiry["reader_subjects"][0]["expires_at"]
        guard_cases.append(("job-access-update.schema.json", update_without_expiry, "reader grant without expiry"))
        update_with_bare_reader = deepcopy(access_update)
        update_with_bare_reader["reader_subjects"][0]["subject"] = "00u-example-reader"
        guard_cases.append(("job-access-update.schema.json", update_with_bare_reader, "bare reader sub without issuer"))
        shared_with_bare_grantor = deepcopy(shared_access)
        shared_with_bare_grantor["reader_subjects"][0]["granted_by_subject"] = "00u-example-user"
        guard_cases.append(("job-access.schema.json", shared_with_bare_grantor, "bare reader grantor sub without issuer"))
        revoke_without_reason = deepcopy(group_revocation)
        del revoke_without_reason["reason"]
        guard_cases.append(("job-group-revocation.schema.json", revoke_without_reason, "group revocation without reason"))
        for schema_name, payload, label in guard_cases:
            validator = Draft202012Validator(
                read_json(CONTRACTS / schema_name),
                registry=registry,
                format_checker=FormatChecker(),
            )
            if validator.is_valid(payload):
                errors.append(f"Contract guard failed: accepted {label}")

    return len(schemas), len(examples)


def local_markdown_links(path: Path) -> set[Path]:
    """Resolve local Markdown targets for CR/ToDo backlink checks."""
    links: set[Path] = set()
    for match in LINK_RE.finditer(path.read_text(encoding="utf-8")):
        target = match.group(1).split("#", 1)[0].strip()
        if not target or target.startswith(("https://", "http://", "mailto:", "tel:", "data:", "#")):
            continue
        if target.startswith("<") and target.endswith(">"):
            target = target[1:-1]
        links.add((path.parent / unquote(target)).resolve())
    return links


def check_change_requests(errors: list[str]) -> int:
    """Keep each implementation impact linked from design to its paired work list."""
    cr_files = sorted((ROOT / "docs" / "change-requests").glob("CR-*.md"))
    todo_files = sorted((ROOT / "docs" / "todos").glob("CR-*.md"))
    ids: dict[str, list[Path]] = {}
    impacts: dict[str, list[Path]] = {}
    metadata: dict[Path, tuple[str | None, str | None, str | None]] = {}
    for path in [*cr_files, *todo_files]:
        match = CR_FILE_RE.fullmatch(path.name)
        if match is None:
            errors.append(f"Invalid CR/ToDo filename: {path.relative_to(ROOT)}")
            continue
        expected_id = match.group(1)
        ids.setdefault(f"{path.parent.name}:{expected_id}", []).append(path)
        header = "\n".join(path.read_text(encoding="utf-8").splitlines()[:15])
        found_ids = CR_ID_RE.findall(header)
        statuses = CR_STATUS_RE.findall(header)
        impact_ids = CR_IMPACT_RE.findall(header)
        if len(found_ids) != 1 or found_ids[0] != expected_id:
            errors.append(f"{path.relative_to(ROOT)}: expected one **ID:** {expected_id} near the top")
        if len(statuses) != 1:
            errors.append(f"{path.relative_to(ROOT)}: expected one **Status:** near the top")
        elif statuses[0].strip() not in CR_STATUSES:
            errors.append(
                f"{path.relative_to(ROOT)}: unsupported **Status:** {statuses[0].strip()!r}; "
                f"use one of {', '.join(CR_STATUSES)}"
            )
        if len(impact_ids) != 1:
            errors.append(f"{path.relative_to(ROOT)}: expected one **Impact ID:** near the top")
        if path.parent.name == "change-requests" and len(impact_ids) == 1:
            impacts.setdefault(impact_ids[0], []).append(path)
        metadata[path] = (
            found_ids[0] if len(found_ids) == 1 else None,
            statuses[0].strip() if len(statuses) == 1 else None,
            impact_ids[0] if len(impact_ids) == 1 else None,
        )

    for duplicate in ids.values():
        if len(duplicate) > 1:
            errors.append("Duplicate CR ID: " + ", ".join(str(path.relative_to(ROOT)) for path in duplicate))
    for duplicate in impacts.values():
        if len(duplicate) > 1:
            errors.append("Duplicate impact ID: " + ", ".join(str(path.relative_to(ROOT)) for path in duplicate))

    cr_by_name = {path.name: path for path in cr_files}
    todo_by_name = {path.name: path for path in todo_files}
    for name in sorted(cr_by_name.keys() ^ todo_by_name.keys()):
        orphan = cr_by_name.get(name) or todo_by_name[name]
        errors.append(f"Unpaired CR/ToDo document: {orphan.relative_to(ROOT)}")

    readme_links = local_markdown_links(ROOT / "README.md")
    index_path = ROOT / "docs" / "TODO.md"
    index_links = local_markdown_links(index_path)
    for name in sorted(cr_by_name.keys() & todo_by_name.keys()):
        cr, todo = cr_by_name[name], todo_by_name[name]
        if metadata.get(cr, (None, None, None))[1] != metadata.get(todo, (None, None, None))[1]:
            errors.append(f"{name}: CR and ToDo statuses differ")
        if metadata.get(cr, (None, None, None))[2] != metadata.get(todo, (None, None, None))[2]:
            errors.append(f"{name}: CR and ToDo impact IDs differ")
        if todo not in local_markdown_links(cr):
            errors.append(f"{cr.relative_to(ROOT)}: missing link to paired ToDo")
        if cr not in local_markdown_links(todo):
            errors.append(f"{todo.relative_to(ROOT)}: missing link to paired CR")
        for source, links in ((ROOT / "README.md", readme_links), (index_path, index_links)):
            if cr not in links or todo not in links:
                errors.append(f"{source.relative_to(ROOT)}: missing direct CR and ToDo links for {name}")
        cr_header = "\n".join(cr.read_text(encoding="utf-8").splitlines()[:15])
        primary_links = CR_PRIMARY_RE.findall(cr_header)
        if len(primary_links) != 1:
            errors.append(f"{cr.relative_to(ROOT)}: expected one linked **Primary design:** near the top")
            continue
        primary = (cr.parent / unquote(primary_links[0].split("#", 1)[0])).resolve()
        if not primary.is_file() or not (
            primary in CR_PRIMARY_DESIGN_FILES
            or any(primary.is_relative_to(folder) for folder in CR_PRIMARY_DESIGN_ROOTS)
        ):
            errors.append(f"{cr.relative_to(ROOT)}: primary design must be a local ADR or design document")
            continue
        primary_links_resolved = local_markdown_links(primary)
        if cr not in primary_links_resolved or todo not in primary_links_resolved:
            errors.append(f"{primary.relative_to(ROOT)}: missing direct CR and ToDo links for {name}")
        impact_id = metadata.get(cr, (None, None, None))[2]
        if impact_id and impact_id not in primary.read_text(encoding="utf-8"):
            errors.append(f"{primary.relative_to(ROOT)}: missing impact ID {impact_id}")
    return len(cr_by_name.keys() & todo_by_name.keys())


def check_markdown(errors: list[str]) -> tuple[int, int]:
    diagrams = 0
    paths = [ROOT / "README.md", ROOT / "AGENTS.md", *sorted((ROOT / "docs").rglob("*.md"))]
    paths.extend(sorted((ROOT / ".agents" / "skills").rglob("SKILL.md")))
    paths.extend(sorted((ROOT / "apps").rglob("*.md")))
    paths.extend(sorted((ROOT / "services").rglob("*.md")))
    paths.extend(sorted((ROOT / "infra").rglob("*.md")))
    paths.extend(sorted((ROOT / "contracts").rglob("*.md")))
    paths.extend(sorted((ROOT / "examples").rglob("*.md")))
    paths.extend(sorted((ROOT / ".github").rglob("*.md")))
    for path in paths:
        content = path.read_text(encoding="utf-8")
        inside = False
        mermaid = False
        mermaid_lines: list[str] = []
        for line_number, line in enumerate(content.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("```"):
                if inside:
                    if mermaid:
                        diagrams += 1
                        first = next((item.strip() for item in mermaid_lines if item.strip()), "")
                        if not first.startswith(MERMAID_STARTS):
                            errors.append(f"{path.relative_to(ROOT)}:{line_number}: unrecognized or empty Mermaid diagram")
                    inside = False
                    mermaid = False
                    mermaid_lines = []
                else:
                    inside = True
                    mermaid = stripped == "```mermaid"
                continue
            if inside:
                if mermaid:
                    mermaid_lines.append(line)
                continue
            for match in LINK_RE.finditer(line):
                target = match.group(1).split("#", 1)[0].strip()
                if not target or target.startswith(("https://", "http://", "mailto:", "tel:", "data:", "#")):
                    continue
                if target.startswith("<") and target.endswith(">"):
                    target = target[1:-1]
                target_path = (path.parent / unquote(target)).resolve()
                if not target_path.is_relative_to(ROOT) or not target_path.exists():
                    errors.append(f"{path.relative_to(ROOT)}:{line_number}: broken local link {target}")
        if inside:
            errors.append(f"{path.relative_to(ROOT)}: unclosed fenced code block")
    return len(paths), diagrams


def check_openapi(errors: list[str]) -> int:
    path = CONTRACTS / "openapi.yaml"
    try:
        with path.open(encoding="utf-8") as handle:
            document = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as exc:
        errors.append(f"{path.relative_to(ROOT)}: {exc}")
        return 0
    if document.get("openapi") != "3.1.0":
        errors.append("OpenAPI document must use version 3.1.0")
    if not document.get("paths") or not document.get("components", {}).get("securitySchemes"):
        errors.append("OpenAPI document is missing paths or security schemes")

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("$ref", "x-event-schema") and isinstance(value, str):
                    if value.startswith("#/"):
                        target: object = document
                        for part in value[2:].split("/"):
                            part = part.replace("~1", "/").replace("~0", "~")
                            if not isinstance(target, dict) or part not in target:
                                errors.append(f"OpenAPI has unresolved reference {value}")
                                break
                            target = target[part]
                    elif not (CONTRACTS / value).resolve().is_file():
                        errors.append(f"OpenAPI has missing local reference {value}")
                else:
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(document)
    operation_ids: set[str] = set()
    for route, item in document.get("paths", {}).items():
        for method, operation in item.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            operation_id = operation.get("operationId")
            if not operation_id or operation_id in operation_ids:
                errors.append(f"OpenAPI route {route} has missing or duplicate operationId")
            operation_ids.add(operation_id)
            if not operation.get("responses"):
                errors.append(f"OpenAPI route {route} {method} has no responses")
    return len(operation_ids)


def main() -> int:
    errors: list[str] = []
    schema_count, example_count = check_contracts(errors)
    markdown_count, diagram_count = check_markdown(errors)
    change_request_count = check_change_requests(errors)
    operation_count = check_openapi(errors)
    if errors:
        for problem in errors:
            print(f"ERROR: {problem}", file=sys.stderr)
        return 1
    print(
        f"Validated {schema_count} JSON Schemas, {example_count} examples, "
        f"{operation_count} OpenAPI operations, {markdown_count} Markdown files, "
        f"{diagram_count} Mermaid fences, and {change_request_count} CR/ToDo pairs."
    )
    print("Live OAuth, MCP, OpenShell policies, and Mermaid rendering require integration checks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
