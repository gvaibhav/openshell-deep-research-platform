#!/usr/bin/env python3
"""Check the design contracts and repository links without calling live services."""

from __future__ import annotations

import json
import hashlib
from copy import deepcopy
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
import yaml


ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
EXAMPLES = ROOT / "examples"
EXAMPLE_SCHEMAS = {
    "job-request.json": "job-request.schema.json",
    "job-policy.json": "job-policy.schema.json",
    "stage-public.json": "stage-manifest.schema.json",
    "stage-enterprise.json": "stage-manifest.schema.json",
    "job-event.json": "job-event.schema.json",
    "evidence.json": "evidence.schema.json",
    "public-evidence.json": "evidence.schema.json",
    "report.json": "report.schema.json",
}
LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
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
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def check_contracts(errors: list[str]) -> tuple[int, int]:
    schemas = {}
    for path in sorted(CONTRACTS.glob("*.schema.json")):
        try:
            schema = read_json(path)
            Draft202012Validator.check_schema(schema)
            if schema["$id"] in schemas:
                errors.append(f"Duplicate schema ID: {schema['$id']}")
            schemas[schema["$id"]] = schema
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append(f"{path.relative_to(ROOT)}: {exc}")

    registry = Registry().with_resources(
        (schema_id, Resource.from_contents(schema))
        for schema_id, schema in schemas.items()
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
        event = examples["job-event.json"]
        evidence = examples["evidence.json"]
        public_evidence = examples["public-evidence.json"]
        report = examples["report.json"]
        public_stage = examples["stage-public.json"]
        enterprise_stage = examples["stage-enterprise.json"]

        if any(
            item["job_id"] != policy["job_id"]
            for item in (event, evidence, public_evidence, report, public_stage, enterprise_stage)
        ):
            errors.append("Example job IDs do not match")
        if request["mode"] != policy["mode"]:
            errors.append("Example request and policy modes do not match")
        if request["sources"] != policy["approved_sources"]:
            errors.append("Example approved sources differ from the request")
        if request["question"] != report["question"]:
            errors.append("Example report question differs from the request")
        if request["public_research_brief"] != policy["public_research_brief"]:
            errors.append("Example public brief differs from approved policy")
        if public_stage["research_brief"] != policy["public_research_brief"]:
            errors.append("Example public stage did not receive approved public brief")
        if enterprise_stage["research_brief"] != request["question"]:
            errors.append("Example enterprise stage did not receive the private question")
        if event.get("evidence_id") != evidence["evidence_id"]:
            errors.append("Example event evidence ID does not resolve")
        known_evidence = {evidence["evidence_id"], public_evidence["evidence_id"]}
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
        ):
            snapshot = fixture.read_bytes()
            if hashlib.sha256(snapshot).hexdigest() != record["content_sha256"]:
                errors.append(f"{fixture.relative_to(ROOT)} does not match evidence digest")
            if record.get("excerpt") and record["excerpt"] not in snapshot.decode("utf-8"):
                errors.append(f"{fixture.relative_to(ROOT)} does not contain the evidence excerpt")
        if enterprise_stage["context_evidence_ids"] != [public_evidence["evidence_id"]]:
            errors.append("Enterprise stage context does not resolve to public evidence")
        if public_stage["approved_sources"] != [source for source in policy["approved_sources"] if source["connector"] == "public_web"]:
            errors.append("Public stage source projection differs from policy")
        if enterprise_stage["approved_sources"] != [source for source in policy["approved_sources"] if source["connector"] != "public_web"]:
            errors.append("Enterprise stage source projection differs from policy")
        for stage in (public_stage, enterprise_stage):
            if stage["policy_version"] != policy["policy_version"]:
                errors.append(f"{stage['stage']} stage has the wrong policy version")
            if not set(stage["allowed_tools"]).issubset(policy["allowed_tools"]):
                errors.append(f"{stage['stage']} stage has a tool outside the job policy")
            if instant(stage["issued_at"]) >= instant(stage["expires_at"]):
                errors.append(f"{stage['stage']} stage has an empty or reversed lifetime")
            if instant(stage["expires_at"]) > instant(policy["expires_at"]):
                errors.append(f"{stage['stage']} stage outlives the job")
            for key, value in stage["limits"].items():
                if value > policy["limits"][key]:
                    errors.append(f"{stage['stage']} stage exceeds job {key}")
        if instant(public_stage["expires_at"]) > instant(enterprise_stage["issued_at"]):
            errors.append("Example stages overlap in time")
        for stage, record in ((public_stage, public_evidence), (enterprise_stage, evidence)):
            retrieved = instant(record["retrieved_at"])
            if not instant(stage["issued_at"]) <= retrieved < instant(stage["expires_at"]):
                errors.append(f"{stage['stage']} evidence falls outside its stage lifetime")
        if not instant(evidence["retrieved_at"]) <= instant(event["at"]) <= instant(report["generated_at"]):
            errors.append("Example event/report timeline is inconsistent")
        if public_stage["attempt_id"] == enterprise_stage["attempt_id"] or public_stage["sandbox_id"] == enterprise_stage["sandbox_id"]:
            errors.append("Example stages reuse an attempt or sandbox identity")
        if public_stage["fencing_generation"] >= enterprise_stage["fencing_generation"]:
            errors.append("Example stage fencing generations do not advance")
        for key, limit in policy["limits"].items():
            if sum(stage["limits"].get(key, 0) for stage in (public_stage, enterprise_stage)) > limit:
                errors.append(f"Stage budgets exceed job {key}")
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
        no_public_brief = deepcopy(request)
        del no_public_brief["public_research_brief"]
        guard_cases.append(("job-request.schema.json", no_public_brief, "combined request without public brief"))
        no_approval = deepcopy(policy)
        del no_approval["public_brief_approval_ref"]
        guard_cases.append(("job-policy.schema.json", no_approval, "combined policy without brief approval"))
        public_with_private_source = deepcopy(public_stage)
        public_with_private_source["approved_sources"].append(policy["approved_sources"][1])
        guard_cases.append(("stage-manifest.schema.json", public_with_private_source, "public stage with private source"))
        private_with_public_source = deepcopy(enterprise_stage)
        private_with_public_source["approved_sources"].append(policy["approved_sources"][0])
        guard_cases.append(("stage-manifest.schema.json", private_with_public_source, "enterprise stage with public source"))
        public_with_private_tool = deepcopy(public_stage)
        public_with_private_tool["allowed_tools"].append("search_slack")
        guard_cases.append(("stage-manifest.schema.json", public_with_private_tool, "public stage with private tool"))
        private_with_public_tool = deepcopy(enterprise_stage)
        private_with_public_tool["allowed_tools"].append("search_public_web")
        guard_cases.append(("stage-manifest.schema.json", private_with_public_tool, "enterprise stage with public tool"))
        evidence_without_call = deepcopy(evidence)
        del evidence_without_call["tool_call_id"]
        guard_cases.append(("evidence.schema.json", evidence_without_call, "evidence without tool call ID"))
        for schema_name, payload, label in guard_cases:
            validator = Draft202012Validator(
                read_json(CONTRACTS / schema_name),
                registry=registry,
                format_checker=FormatChecker(),
            )
            if validator.is_valid(payload):
                errors.append(f"Contract guard failed: accepted {label}")

    return len(schemas), len(examples)


def check_markdown(errors: list[str]) -> tuple[int, int]:
    diagrams = 0
    paths = [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]
    paths.extend(sorted((ROOT / "apps").rglob("*.md")))
    paths.extend(sorted((ROOT / "services").rglob("*.md")))
    paths.extend(sorted((ROOT / "infra").rglob("*.md")))
    paths.extend(sorted((ROOT / "contracts").rglob("*.md")))
    paths.extend(sorted((ROOT / "examples").rglob("*.md")))
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
    operation_count = check_openapi(errors)
    if errors:
        for problem in errors:
            print(f"ERROR: {problem}", file=sys.stderr)
        return 1
    print(
        f"Validated {schema_count} JSON Schemas, {example_count} examples, "
        f"{operation_count} OpenAPI operations, {markdown_count} Markdown files, "
        f"and {diagram_count} Mermaid fences."
    )
    print("Live OAuth, MCP, OpenShell policies, and Mermaid rendering require integration checks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
