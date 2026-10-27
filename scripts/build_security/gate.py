"""Fail-closed build and release evidence gates (OPS-10, OPS-12).

This module validates evidence produced by scan.py. It cannot prove that a
registry digest is the image deployed, or that a named exception approver is an
authorized security owner; those are protected release and branch-policy gates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

TRIVY_VERSION = "0.76.1"
MAX_DB_AGE = timedelta(hours=36)
MAX_SCAN_AGE = timedelta(hours=24)
MAX_KEV_FETCH_AGE = timedelta(hours=1)
MAX_EXCEPTION_LIFE = timedelta(days=30)
IMAGE_REF = re.compile(r"^[a-z0-9][a-z0-9._:/-]*@sha256:[a-f0-9]{64}$")
IMAGE_PLATFORM = re.compile(r"^linux/(?:amd64|arm64)$")
PIN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*(?:\[[A-Za-z0-9_,.-]+\])?==[A-Za-z0-9.!+_~-]+$")
HASH = re.compile(r"^--hash=sha256:[a-f0-9]{64}$")
REQUIRED_ROLES = {"spike_worker", "openshell_gateway", "openshell_supervisor", "openshell_runtime"}
WORKER_DIRECT_KEYS = {
    "deepagents": "deepagents",
    "langchain": "langchain",
    "langchain-core": "langchain_core",
    "langgraph": "langgraph",
    "langchain-openai": "langchain_openai",
}
WORKER_LOCK = "spikes/full_graph/requirements-worker.lock"
WORKER_DIRECT = "spikes/full_graph/requirements-worker.txt"
WORKER_VERSIONS = "spikes/full_graph/version-manifest.json"
DEV_LOCK_NAME = "requirements-dev.lock"


class GateError(ValueError):
    """A required security check is missing, stale, or has a blocking finding."""


def normalize_pip_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError as exc:
        raise GateError(f"missing {path}") from exc


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GateError(f"missing {label}: {path}") from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise GateError(f"invalid {label}: {path}") from exc
    if not isinstance(value, dict):
        raise GateError(f"invalid {label}: expected JSON object")
    return value


def require_checksum(path: Path, expected: object, label: str) -> None:
    if not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected):
        raise GateError(f"missing {label} checksum")
    if digest(path) != expected:
        raise GateError(f"{label} checksum mismatch: {path}")


def parse_time(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise GateError(f"missing {label} timestamp")
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise GateError(f"invalid {label} timestamp") from exc
    if result.tzinfo is None:
        raise GateError(f"{label} timestamp must have a timezone")
    return result.astimezone(UTC)


def require_fresh(value: object, label: str, now: datetime, max_age: timedelta) -> datetime:
    timestamp = parse_time(value, label)
    age = now - timestamp
    if age < -timedelta(minutes=5) or age > max_age:
        raise GateError(f"{label} stale or in the future: {timestamp.isoformat()}")
    return timestamp


def validate_pip_lock(path: Path, *, require_hashes: bool = False) -> dict[str, str]:
    """Require exact pins in a pip-format lock.

    Completeness is checked again in CI with a no-dependency install and `pip check`.
    The release worker lock requires a SHA-256 hash for every pin, matching its
    Dockerfile's ``pip --require-hashes`` install. The CI tool lock can be pin-only.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise GateError(f"missing dependency lock: {path}") from exc
    packages: dict[str, str] = {}
    last_key: str | None = None
    hashes_for_pin = 0
    for number, raw in enumerate(lines, 1):
        line = raw.partition("#")[0].strip().removesuffix("\\").strip()
        if not line:
            continue
        if HASH.fullmatch(line):
            if last_key is None:
                raise GateError(f"orphan lock hash at {path}:{number}")
            hashes_for_pin += 1
            continue
        if not PIN.fullmatch(line):
            raise GateError(f"dependency lock must pin exact package versions at {path}:{number}")
        name, version = line.split("==", 1)
        key = normalize_pip_name(name)
        if require_hashes and last_key is not None and hashes_for_pin == 0:
            raise GateError(f"missing SHA-256 hash for {last_key} in {path}")
        if key in packages:
            raise GateError(f"duplicate dependency pin {name} in {path}")
        packages[key] = version
        last_key = key
        hashes_for_pin = 0
    if not packages:
        raise GateError(f"empty dependency lock: {path}")
    if require_hashes and hashes_for_pin == 0:
        raise GateError(f"missing SHA-256 hash for {last_key} in {path}")
    return packages


def numeric_release_version(value: str, label: str) -> tuple[int, ...]:
    """Accept the numeric PEP 440 release subset used by the dev manifest."""
    if not re.fullmatch(r"\d+(?:\.\d+)*", value):
        raise GateError(f"unsupported {label} version: {value!r}")
    parts = tuple(int(part) for part in value.split("."))
    while len(parts) > 1 and parts[-1] == 0:
        parts = parts[:-1]
    return parts


def validate_dev_inputs(lock_path: Path) -> dict[str, str]:
    """Check every ranged development source requirement against its scanned pin.

    The source manifest intentionally supports only simple numeric release
    ranges. An unsupported marker, extra, epoch, or pre-release fails closed
    until this validator and its tests are deliberately extended.
    """
    locked = validate_pip_lock(lock_path)
    direct_path = lock_path.with_suffix(".txt")
    try:
        lines = direct_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise GateError(f"missing development direct manifest: {direct_path}") from exc
    seen: set[str] = set()
    for number, raw in enumerate(lines, 1):
        line = raw.partition("#")[0].strip()
        if not line:
            continue
        match = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9_.-]*)(.*)", line)
        if match is None:
            raise GateError(f"invalid development direct requirement at {direct_path}:{number}")
        name = normalize_pip_name(match.group(1))
        clauses = match.group(2).strip().split(",")
        if name in seen or not clauses or not all(clause.strip() for clause in clauses):
            raise GateError(f"duplicate or unbounded development direct requirement: {name}")
        seen.add(name)
        pinned = locked.get(name)
        if pinned is None:
            raise GateError(f"development direct dependency missing from lock: {name}")
        release = numeric_release_version(pinned, "development lock")
        for clause in clauses:
            bound = re.fullmatch(r"\s*(>=|<=|==|>|<)\s*(\d+(?:\.\d+)*)\s*", clause)
            if bound is None:
                raise GateError(f"unsupported development direct range for {name}: {clause!r}")
            required = numeric_release_version(bound.group(2), "development direct")
            operator = bound.group(1)
            satisfied = {
                ">=": release >= required,
                "<=": release <= required,
                "==": release == required,
                ">": release > required,
                "<": release < required,
            }[operator]
            if not satisfied:
                raise GateError(
                    f"development direct range for {name} is not satisfied by lock pin {pinned}"
                )
    if not seen:
        raise GateError(f"empty development direct manifest: {direct_path}")
    return locked


def safe_child(root: Path, relative: object, label: str) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise GateError(f"invalid {label} path")
    resolved_root = root.resolve()
    candidate = (resolved_root / relative).resolve()
    if not candidate.is_relative_to(resolved_root):
        raise GateError(f"{label} path escapes its evidence root")
    return candidate


def validate_worker_inputs(repository_root: Path) -> dict[str, str]:
    """Bind the worker's direct pins and version claim to its hashed install lock."""
    lock = validate_pip_lock(
        safe_child(repository_root, WORKER_LOCK, "worker dependency lock"),
        require_hashes=True,
    )
    direct = validate_pip_lock(safe_child(repository_root, WORKER_DIRECT, "worker direct pins"))
    if set(direct) != set(WORKER_DIRECT_KEYS):
        raise GateError("worker direct pins differ from the reviewed versioned package set")
    versions = read_json(safe_child(repository_root, WORKER_VERSIONS, "worker version manifest"),
                         "worker version manifest")
    for name, version_key in WORKER_DIRECT_KEYS.items():
        if direct[name] != lock.get(name):
            raise GateError(f"worker direct pin does not match hash lock: {name}")
        if versions.get(version_key) != lock[name]:
            raise GateError(f"worker version manifest does not match hash lock: {name}")
    if versions.get("python_minor") != "3.13":
        raise GateError("worker version manifest Python target does not match lock")
    return lock


def validate_manifest(path: Path, repository_root: Path) -> dict[str, Any]:
    manifest = read_json(path, "release manifest")
    if manifest.get("schema_version") != 1 or manifest.get("profile") != "spike":
        raise GateError("release manifest must use the supported spike profile and schema v1")
    if not isinstance(manifest.get("uses_kubernetes"), bool):
        raise GateError("release manifest must state uses_kubernetes")
    if manifest.get("gcp_host_relay_enabled") is not False:
        raise GateError("GCP host relay must be explicitly disabled until its adapter and host lock qualify")
    images = manifest.get("images")
    if not isinstance(images, dict):
        raise GateError("release manifest lacks image digests")
    required = set(REQUIRED_ROLES)
    if manifest["uses_kubernetes"]:
        required.add("agent_sandbox_controller")
    missing = required - set(images)
    if missing:
        raise GateError(f"release manifest lacks required image digest: {', '.join(sorted(missing))}")
    for role, ref in images.items():
        if not isinstance(role, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", role):
            raise GateError(f"invalid image role: {role!r}")
        if not isinstance(ref, str) or not IMAGE_REF.fullmatch(ref):
            raise GateError(f"missing immutable image digest for {role}: {ref!r}")
    platforms = manifest.get("platforms")
    if not isinstance(platforms, dict) or set(platforms) != set(images):
        raise GateError("release manifest lacks an exact platform for every image")
    for role, platform in platforms.items():
        if not isinstance(platform, str) or not IMAGE_PLATFORM.fullmatch(platform):
            raise GateError(f"invalid image platform for {role}: {platform!r}")
    if platforms["spike_worker"] != "linux/arm64":
        raise GateError("spike worker platform must match the Linux ARM64 resolved lock target")
    locks = manifest.get("dependency_locks")
    if not isinstance(locks, list) or not locks or not all(isinstance(x, str) for x in locks):
        raise GateError("release manifest lacks dependency lock paths")
    if WORKER_LOCK not in locks:
        raise GateError("release manifest lacks spike worker dependency lock")
    if len(set(locks)) != len(locks):
        raise GateError("duplicate dependency lock path")
    for lock in locks:
        lock_path = safe_child(repository_root, lock, "dependency lock")
        if lock == DEV_LOCK_NAME:
            validate_dev_inputs(lock_path)
        else:
            validate_pip_lock(lock_path, require_hashes=lock == WORKER_LOCK)
    validate_worker_inputs(repository_root)
    return manifest


def validate_scanner_version(data: dict[str, Any], now: datetime) -> None:
    if data.get("Version") != TRIVY_VERSION:
        raise GateError(f"scanner version must be Trivy {TRIVY_VERSION}")
    db = data.get("VulnerabilityDB")
    if not isinstance(db, dict) or not isinstance(db.get("Version"), int):
        raise GateError("missing vulnerability database metadata")
    updated = require_fresh(db.get("UpdatedAt"), "advisory database", now, MAX_DB_AGE)
    downloaded = require_fresh(db.get("DownloadedAt"), "advisory database download", now, MAX_DB_AGE)
    if downloaded < updated:
        raise GateError("advisory database download predates its update")


def validate_kev(data: dict[str, Any]) -> set[str]:
    if not isinstance(data.get("catalogVersion"), str) or not data.get("catalogVersion"):
        raise GateError("invalid KEV catalog version")
    parse_time(data.get("dateReleased"), "KEV release")
    vulnerabilities = data.get("vulnerabilities")
    if not isinstance(vulnerabilities, list) or not vulnerabilities:
        raise GateError("missing KEV catalog vulnerabilities")
    count = data.get("count")
    if type(count) is not int or count <= 0 or count != len(vulnerabilities):
        raise GateError("KEV declared count does not match catalog entries")
    required_fields = (
        "cveID", "vendorProject", "product", "vulnerabilityName", "dateAdded",
        "shortDescription", "requiredAction", "dueDate", "knownRansomwareCampaignUse",
        "notes",
    )
    cves: set[str] = set()
    for entry in vulnerabilities:
        if not isinstance(entry, dict) or not all(
            isinstance(entry.get(field), str) and entry[field].strip()
            for field in required_fields
        ):
            raise GateError("incomplete KEV catalog entry")
        cve = entry["cveID"].upper()
        if not re.fullmatch(r"CVE-\d{4}-\d{4,}", cve):
            raise GateError("invalid KEV CVE identifier")
        if cve in cves:
            raise GateError(f"duplicate KEV CVE identifier: {cve}")
        try:
            date.fromisoformat(entry["dateAdded"])
            date.fromisoformat(entry["dueDate"])
        except ValueError as exc:
            raise GateError(f"invalid KEV entry dates for {cve}") from exc
        cves.add(cve)
    return cves


def load_decisions(path: Path | None, now: datetime) -> list[dict[str, Any]]:
    if path is None:
        return []
    data = read_json(path, "finding dispositions")
    if data.get("schema_version") != 1 or not isinstance(data.get("decisions"), list):
        raise GateError("invalid finding dispositions schema")
    decisions = data["decisions"]
    for item in decisions:
        if not isinstance(item, dict):
            raise GateError("finding disposition must be an object")
        finding_id = item.get("vulnerability_id", "unknown finding")
        required = ("artifact", "vulnerability_id", "package", "installed_version",
                    "ticket", "reason")
        if not all(isinstance(item.get(key), str) and item[key].strip() for key in required):
            raise GateError(f"incomplete finding disposition for {finding_id}")
        decision = item.get("decision")
        if decision not in {"not_affected", "temporary_exception", "triage"}:
            raise GateError(f"invalid finding disposition for {finding_id}")
        if "platform" in item and (
            not isinstance(item["platform"], str) or not IMAGE_PLATFORM.fullmatch(item["platform"])
        ):
            raise GateError(f"invalid finding disposition platform for {finding_id}")
        if decision == "triage":
            if not isinstance(item.get("owner"), str) or not item["owner"].strip():
                raise GateError(f"triage owner missing for {finding_id}")
            due = parse_time(item.get("due_at"), "triage due")
            if due <= now:
                raise GateError(f"triage due date expired for {finding_id}")
            continue
        exception_fields = ("security_owner", "vendor_evidence", "mitigation")
        if not all(isinstance(item.get(key), str) and item[key].strip()
                   for key in exception_fields):
            raise GateError(f"incomplete finding disposition for {finding_id}")
        approved = parse_time(item.get("approved_at"), "exception approval")
        expires = parse_time(item.get("expires_at"), "exception expiry")
        if approved > now + timedelta(minutes=5) or expires <= approved:
            raise GateError(f"invalid exception dates for {finding_id}")
        if expires - approved > MAX_EXCEPTION_LIFE:
            raise GateError(f"exception lifetime exceeds 30 days for {finding_id}")
        if expires <= now:
            raise GateError(f"expired exception for {finding_id}")
    return decisions


def check_findings(
    report: dict[str, Any], artifact: str, kev: set[str], decisions: list[dict[str, Any]],
    platform: str | None = None,
) -> tuple[int, int]:
    accepted = 0
    lower = 0
    for result in report["Results"]:
        vulnerabilities = result.get("Vulnerabilities")
        if vulnerabilities is None:
            vulnerabilities = []
        if not isinstance(vulnerabilities, list):
            raise GateError(f"invalid scan vulnerabilities for {artifact}")
        for finding in vulnerabilities:
            if not isinstance(finding, dict):
                raise GateError(f"invalid scan finding for {artifact}")
            primary = finding.get("VulnerabilityID")
            severity = finding.get("Severity")
            package = finding.get("PkgName")
            version = finding.get("InstalledVersion")
            aliases = finding.get("VendorIDs")
            if aliases is None:
                aliases = []
            if (not isinstance(primary, str) or not primary or
                severity not in {"UNKNOWN", "LOW", "MEDIUM", "HIGH", "CRITICAL"} or
                not isinstance(package, str) or not package or
                not isinstance(version, str) or not version or
                not isinstance(aliases, list) or not all(
                    isinstance(a, str) and a.strip() for a in aliases
                )):
                raise GateError(f"incomplete vulnerability finding for {artifact}")
            ids = {primary.upper(), *(alias.upper() for alias in aliases)}
            kev_hits = kev & ids
            blocking = bool(kev_hits) or severity in {"UNKNOWN", "HIGH", "CRITICAL"}
            matched = [d for d in decisions if d["artifact"] == artifact and
                       d["vulnerability_id"].upper() in ids and d["package"] == package and
                       d["installed_version"] == version and d.get("platform") == platform]
            display = min(kev_hits) if kev_hits else primary
            if len(matched) > 1:
                raise GateError(f"duplicate disposition for {display} in {artifact}")
            if blocking:
                if len(matched) == 1 and matched[0]["decision"] != "triage":
                    accepted += 1
                    continue
                raise GateError(
                    f"policy-blocking finding {display} ({severity}) in {artifact}: "
                    f"{package}=={version}"
                )
            lower += 1
            if len(matched) == 1:
                accepted += 1
                continue
            raise GateError(
                f"lower-severity finding {display} ({severity}) has no scoped owner and due date "
                f"in {artifact}: {package}=={version}"
            )
    return accepted, lower


def image_package_inventory(report: dict[str, Any], role: str) -> Counter[str]:
    """Require both observed scanner ecosystems and retain package multiplicity."""
    results = report.get("Results")
    if not isinstance(results, list) or not results:
        raise GateError(f"no package coverage observed in scan for {role}")
    classes: Counter[str] = Counter()
    purls: Counter[str] = Counter()
    for result in results:
        if not isinstance(result, dict):
            raise GateError(f"invalid package result in scan for {role}")
        package_class = result.get("Class")
        if package_class not in {"os-pkgs", "lang-pkgs"}:
            raise GateError(f"unexpected package class in scan for {role}")
        if not isinstance(result.get("Type"), str) or not result["Type"].strip():
            raise GateError(f"missing package ecosystem in scan for {role}")
        packages = result.get("Packages")
        if not isinstance(packages, list) or not packages:
            raise GateError(f"empty {package_class} package coverage in scan for {role}")
        classes[package_class] += len(packages)
        for package in packages:
            if not isinstance(package, dict) or not all(
                isinstance(package.get(field), str) and package[field]
                for field in ("Name", "Version")
            ):
                raise GateError(f"invalid package inventory in scan for {role}")
            identifier = package.get("Identifier")
            purl = identifier.get("PURL") if isinstance(identifier, dict) else None
            if not isinstance(purl, str) or not purl.startswith("pkg:"):
                raise GateError(f"scan package lacks a PURL in {role}")
            purls[purl] += 1
    if not classes["os-pkgs"]:
        raise GateError(f"missing observed OS package coverage (os-pkgs) for {role}")
    if not classes["lang-pkgs"]:
        raise GateError(f"missing observed language package coverage (lang-pkgs) for {role}")
    return purls


def sbom_package_inventory(sbom: dict[str, Any], ref: str, platform: str,
                           role: str) -> Counter[str]:
    if sbom.get("bomFormat") != "CycloneDX" or not isinstance(sbom.get("specVersion"), str):
        raise GateError(f"incomplete CycloneDX SBOM for {role}")
    metadata = sbom.get("metadata")
    component = metadata.get("component") if isinstance(metadata, dict) else None
    if not isinstance(component, dict) or component.get("type") != "container" or (
        component.get("name") != ref
    ):
        raise GateError(f"SBOM target digest does not match {role}")
    purl = component.get("purl")
    if not isinstance(purl, str):
        raise GateError(f"SBOM OCI digest is missing for {role}")
    parsed = urlsplit(purl)
    match = re.fullmatch(r"oci/[^@?]+@sha256:([a-f0-9]{64})", parsed.path)
    if parsed.scheme != "pkg" or match is None or match.group(1) != ref.rsplit("@sha256:", 1)[1]:
        raise GateError(f"SBOM OCI digest does not match {role}")
    if parse_qs(parsed.query).get("arch") != [platform.split("/", 1)[1]]:
        raise GateError(f"SBOM platform does not match {role}")
    components = sbom.get("components")
    if not isinstance(components, list) or not components:
        raise GateError(f"incomplete CycloneDX SBOM for {role}")
    purls: Counter[str] = Counter()
    for item in components:
        if not isinstance(item, dict):
            raise GateError(f"invalid SBOM component for {role}")
        if item.get("type") != "library":
            continue
        item_purl = item.get("purl")
        if not isinstance(item_purl, str) or not item_purl.startswith("pkg:"):
            raise GateError(f"SBOM library lacks a PURL for {role}")
        purls[item_purl] += 1
    if not purls:
        raise GateError(f"SBOM package inventory is empty for {role}")
    return purls


def validate_archive_inventory(inventory: dict[str, Any], ref: str, platform: str,
                               role: str, now: datetime) -> None:
    """Require complete effective-rootfs coverage and reject undispositioned candidates.

    The scanner's Docker export is the trusted observation point. This first
    contract has no approval format for retained archives: any candidate
    blocks until a separately reviewed content-scan/disposition path exists.
    """
    label = f"archive inventory for {role}"
    if inventory.get("schema_version") != 2 or inventory.get("source") != "docker-container-export":
        raise GateError(f"invalid {label} schema or source")
    if inventory.get("ref") != ref or inventory.get("platform") != platform:
        raise GateError(f"{label} digest or platform does not match manifest")
    image_id = inventory.get("resolved_image_id")
    if not isinstance(image_id, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", image_id):
        raise GateError(f"{label} lacks a resolved image ID")
    for field in ("resolved_descriptor_digest", "container_image_id"):
        observed = inventory.get(field)
        if not isinstance(observed, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", observed):
            raise GateError(f"{label} lacks {field}")
    rootfs_diff_ids = inventory.get("rootfs_diff_ids")
    if not isinstance(rootfs_diff_ids, list) or not 1 <= len(rootfs_diff_ids) <= 1000 or not all(
        isinstance(value, str) and re.fullmatch(r"sha256:[a-f0-9]{64}", value)
        for value in rootfs_diff_ids
    ):
        raise GateError(f"{label} lacks exact rootfs diff IDs")
    if (inventory.get("observed_os"), inventory.get("observed_architecture")) != tuple(
        platform.split("/")
    ):
        raise GateError(f"{label} observed image platform does not match manifest")
    require_fresh(inventory.get("captured_at"), label, now, MAX_SCAN_AGE)
    if inventory.get("complete") is not True:
        raise GateError(f"{label} is incomplete")
    export_sha = inventory.get("export_sha256")
    if not isinstance(export_sha, str) or not re.fullmatch(r"[a-f0-9]{64}", export_sha):
        raise GateError(f"{label} lacks an export hash")
    export_bytes = inventory.get("export_bytes")
    entries = inventory.get("entries_seen")
    files = inventory.get("regular_files_seen")
    if type(export_bytes) is not int or export_bytes < 10240 or export_bytes % 512 or (
        export_bytes > 8 * 1024**3
    ) or type(entries) is not int or entries < 1 or entries > 1_000_000 or (
        type(files) is not int or files < 1 or files > entries
    ):
        raise GateError(f"{label} lacks complete filesystem entry coverage")
    candidates = inventory.get("candidates")
    if not isinstance(candidates, list) or len(candidates) > 10_000:
        raise GateError(f"{label} has incomplete candidate coverage")
    seen: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise GateError(f"{label} has an invalid candidate")
        path = candidate.get("path")
        if not isinstance(path, str) or len(path) > 4096 or not path.startswith("/") or (
            "\\" in path or "\x00" in path
        ) or any(part in ("", ".", "..") for part in path[1:].split("/")) or path in seen:
            raise GateError(f"{label} has an unsafe candidate path")
        seen.add(path)
        if candidate.get("reason") not in {
            "archive_name", "zip_magic", "vendored_manifest", "vendored_file",
        }:
            raise GateError(f"{label} has an invalid candidate reason")
        kind = candidate.get("kind")
        if kind == "regular":
            size = candidate.get("size")
            sha = candidate.get("sha256")
            if type(size) is not int or size < 0 or size > export_bytes or (
                not isinstance(sha, str) or not re.fullmatch(r"[a-f0-9]{64}", sha)
            ):
                raise GateError(f"{label} has an unhashed regular candidate")
        elif kind in ("symlink", "hardlink"):
            target = candidate.get("link_target")
            if candidate.get("size") != 0 or candidate.get("sha256") is not None or (
                not isinstance(target, str) or not target or len(target) > 4096 or "\x00" in target
            ):
                raise GateError(f"{label} has an invalid link candidate")
        else:
            raise GateError(f"{label} has an invalid candidate file type")
    if candidates:
        raise GateError(f"unexamined archive candidate in {role}: {candidates[0]['path']}")


def validate_scan_inventory_identity(report: dict[str, Any], inventory: dict[str, Any],
                                     role: str) -> None:
    """Bind Trivy's observed image/layers to Docker's exported platform child."""
    metadata = report.get("Metadata")
    config = metadata.get("ImageConfig") if isinstance(metadata, dict) else None
    scan_image_id = metadata.get("ImageID") if isinstance(metadata, dict) else None
    if not isinstance(scan_image_id, str) or not re.fullmatch(
        r"sha256:[a-f0-9]{64}", scan_image_id
    ) or scan_image_id != inventory.get("container_image_id"):
        raise GateError(f"scan image identity does not match archive inventory for {role}")
    scan_diff_ids = metadata.get("DiffIDs") if isinstance(metadata, dict) else None
    rootfs = config.get("rootfs") if isinstance(config, dict) else None
    config_diff_ids = rootfs.get("diff_ids") if isinstance(rootfs, dict) else None
    if not isinstance(rootfs, dict) or rootfs.get("type") != "layers":
        raise GateError(f"scan rootfs identity is missing for {role}")
    for observed in (scan_diff_ids, config_diff_ids):
        if not isinstance(observed, list) or not 1 <= len(observed) <= 1000 or not all(
            isinstance(value, str) and re.fullmatch(r"sha256:[a-f0-9]{64}", value)
            for value in observed
        ):
            raise GateError(f"scan rootfs diff IDs are incomplete for {role}")
    if scan_diff_ids != config_diff_ids or scan_diff_ids != inventory.get("rootfs_diff_ids"):
        raise GateError(f"scan rootfs identity does not match archive inventory for {role}")


def validate_sbom_inventory_identity(sbom: dict[str, Any], report: dict[str, Any],
                                     inventory: dict[str, Any], role: str) -> None:
    """Bind Trivy's CycloneDX root to the scan and exported platform child.

    Trivy 0.76.1 sorts CycloneDX DiffID properties. Its scan metadata and
    Docker's image inspect retain layer order, which is checked separately.
    """
    metadata = sbom.get("metadata")
    component = metadata.get("component") if isinstance(metadata, dict) else None
    properties = component.get("properties") if isinstance(component, dict) else None
    if not isinstance(properties, list) or not 1 <= len(properties) <= 10_000:
        raise GateError(f"SBOM root properties are missing or incomplete for {role}")
    image_ids: list[str] = []
    diff_ids: list[str] = []
    for prop in properties:
        if not isinstance(prop, dict) or not isinstance(prop.get("name"), str) or (
            not isinstance(prop.get("value"), str) or not prop["name"] or not prop["value"]
        ):
            raise GateError(f"SBOM root properties are malformed for {role}")
        if prop["name"] == "aquasecurity:trivy:ImageID":
            image_ids.append(prop["value"])
        elif prop["name"] == "aquasecurity:trivy:DiffID":
            diff_ids.append(prop["value"])
    scan_metadata = report["Metadata"]
    expected_image_id = inventory["container_image_id"]
    if len(image_ids) != 1 or not re.fullmatch(r"sha256:[a-f0-9]{64}", image_ids[0]) or (
        image_ids[0] != scan_metadata["ImageID"] or image_ids[0] != expected_image_id
    ):
        raise GateError(f"SBOM root ImageID does not match scan/archive inventory for {role}")
    if not 1 <= len(diff_ids) <= 1000 or not all(
        re.fullmatch(r"sha256:[a-f0-9]{64}", value) for value in diff_ids
    ) or Counter(diff_ids) != Counter(scan_metadata["DiffIDs"]) or (
        Counter(diff_ids) != Counter(inventory["rootfs_diff_ids"])
    ):
        raise GateError(f"SBOM root DiffID set does not match scan/archive inventory for {role}")


def validate_release(
    manifest_path: Path,
    evidence_dir: Path,
    repository_root: Path,
    exceptions_path: Path | None = None,
    now: datetime | None = None,
) -> dict[str, int]:
    now = (now or datetime.now(UTC)).astimezone(UTC)
    manifest = validate_manifest(manifest_path, repository_root)
    evidence = read_json(evidence_dir / "evidence.json", "release scan evidence")
    if evidence.get("schema_version") != 1:
        raise GateError("invalid release scan evidence schema")
    require_checksum(manifest_path, evidence.get("manifest_sha256"), "manifest")
    hashes = evidence.get("locks")
    if not isinstance(hashes, dict) or set(hashes) != set(manifest["dependency_locks"]):
        raise GateError("missing dependency lock checksums")
    for lock in manifest["dependency_locks"]:
        require_checksum(safe_child(repository_root, lock, "dependency lock"), hashes[lock], "lock")
    worker_packages = validate_worker_inputs(repository_root)
    version_path = safe_child(evidence_dir, evidence.get("trivy_version_file"), "scanner version")
    require_checksum(version_path, evidence.get("trivy_version_sha256"), "scanner version")
    validate_scanner_version(read_json(version_path, "scanner version"), now)
    kev_path = safe_child(evidence_dir, evidence.get("kev_file"), "KEV")
    if not kev_path.is_file():
        raise GateError(f"missing KEV feed: {kev_path}")
    require_checksum(kev_path, evidence.get("kev_sha256"), "KEV")
    require_fresh(evidence.get("kev_fetched_at"), "KEV fetch", now, MAX_KEV_FETCH_AGE)
    kev = validate_kev(read_json(kev_path, "KEV feed"))
    decisions = load_decisions(exceptions_path, now)
    entries = evidence.get("images")
    if not isinstance(entries, list):
        raise GateError("missing image scan evidence")
    by_role = {item.get("role"): item for item in entries if isinstance(item, dict)}
    if len(by_role) != len(entries) or set(by_role) != set(manifest["images"]):
        raise GateError("image scan evidence does not cover every manifest digest")
    accepted = 0
    lower = 0
    for role, ref in manifest["images"].items():
        item = by_role[role]
        if item.get("ref") != ref:
            raise GateError(f"scan digest does not match manifest for {role}")
        platform = manifest["platforms"][role]
        if item.get("platform") != platform:
            raise GateError(f"scan platform does not match manifest for {role}")
        require_fresh(item.get("scanned_at"), f"scan for {role}", now, MAX_SCAN_AGE)
        if item.get("package_types") != ["os", "library"]:
            raise GateError(f"incomplete OS/language package coverage for {role}")
        scan_path = safe_child(evidence_dir, item.get("scan_file"), "scan")
        if not scan_path.is_file():
            raise GateError(f"missing scan for {role}: {scan_path}")
        require_checksum(scan_path, item.get("scan_sha256"), "scan")
        report = read_json(scan_path, "scan report")
        if report.get("ArtifactName") != ref or report.get("ArtifactType") != "container_image":
            raise GateError(f"scan target does not match image digest for {role}")
        metadata = report.get("Metadata")
        config = metadata.get("ImageConfig") if isinstance(metadata, dict) else None
        if not isinstance(config, dict) or (
            config.get("os"), config.get("architecture")
        ) != tuple(platform.split("/")):
            raise GateError(f"scan platform does not match image for {role}")
        scan_purls = image_package_inventory(report, role)
        results = report["Results"]
        if role == "spike_worker":
            observed_python: dict[str, set[str]] = {}
            for result in results:
                if not isinstance(result, dict) or (
                    result.get("Class"), result.get("Type")
                ) != ("lang-pkgs", "python-pkg"):
                    continue
                packages = result.get("Packages")
                if not isinstance(packages, list):
                    raise GateError("worker image has incomplete Python package coverage")
                for package in packages:
                    if not isinstance(package, dict) or not isinstance(package.get("Name"), str) or (
                        not isinstance(package.get("Version"), str)
                    ):
                        raise GateError("worker image has invalid Python package inventory")
                    observed_python.setdefault(normalize_pip_name(package["Name"]), set()).add(
                        package["Version"]
                    )
            for name, version in worker_packages.items():
                if version not in observed_python.get(name, set()):
                    raise GateError(f"worker image lacks exact locked Python package {name}=={version}")
        sbom_path = safe_child(evidence_dir, item.get("sbom_file"), "SBOM")
        if not sbom_path.is_file():
            raise GateError(f"missing SBOM for {role}: {sbom_path}")
        require_checksum(sbom_path, item.get("sbom_sha256"), "SBOM")
        sbom = read_json(sbom_path, "SBOM")
        sbom_purls = sbom_package_inventory(sbom, ref, platform, role)
        if scan_purls != sbom_purls:
            raise GateError(f"SBOM package inventory does not match scan for {role}")
        archive_path = safe_child(evidence_dir, item.get("archive_inventory_file"),
                                  "archive inventory")
        if not archive_path.is_file():
            raise GateError(f"missing archive inventory for {role}: {archive_path}")
        if archive_path.stat().st_size > 64 * 1024 * 1024:
            raise GateError(f"archive inventory for {role} exceeds evidence size limit")
        require_checksum(archive_path, item.get("archive_inventory_sha256"), "archive inventory")
        archive_inventory = read_json(archive_path, "archive inventory")
        validate_archive_inventory(archive_inventory, ref, platform, role, now)
        validate_scan_inventory_identity(report, archive_inventory, role)
        validate_sbom_inventory_identity(sbom, report, archive_inventory, role)
        a, l = check_findings(report, ref, kev, decisions, platform)
        accepted += a
        lower += l
    return {"images_checked": len(by_role), "accepted_dispositions": accepted,
            "lower_severity_findings": lower, "blocking_findings": 0}


def validate_dependency_report(
    lock_path: Path,
    report_path: Path,
    version_path: Path,
    kev_path: Path,
    kev_fetched_at: str,
    exceptions_path: Path | None = None,
    now: datetime | None = None,
) -> dict[str, int]:
    now = (now or datetime.now(UTC)).astimezone(UTC)
    if lock_path.name == DEV_LOCK_NAME:
        locked = validate_dev_inputs(lock_path)
    else:
        locked = validate_pip_lock(lock_path, require_hashes=lock_path.name == "requirements-worker.lock")
    if lock_path.name == "requirements-worker.lock":
        validate_worker_inputs(lock_path.resolve().parents[2])
    validate_scanner_version(read_json(version_path, "scanner version"), now)
    require_fresh(kev_fetched_at, "KEV fetch", now, MAX_KEV_FETCH_AGE)
    kev = validate_kev(read_json(kev_path, "KEV feed"))
    report = read_json(report_path, "dependency scan")
    if report.get("ArtifactType") != "filesystem":
        raise GateError("dependency scan target must be a filesystem")
    results = report.get("Results")
    if not isinstance(results, list) or len(results) != 1:
        raise GateError("dependency scan lacks isolated requirements.txt package coverage")
    result = results[0]
    if not isinstance(result, dict) or (
        result.get("Target"), result.get("Class"), result.get("Type")
    ) != ("requirements.txt", "lang-pkgs", "pip"):
        raise GateError("dependency scan target/ecosystem must be requirements.txt pip packages")
    packages = result.get("Packages")
    if not isinstance(packages, list) or not packages:
        raise GateError("dependency scan has no pip package coverage")
    observed: dict[str, str] = {}
    for package in packages:
        if not isinstance(package, dict) or not isinstance(package.get("Name"), str) or (
            not isinstance(package.get("Version"), str) or not package["Version"]
        ):
            raise GateError("invalid dependency package record")
        key = normalize_pip_name(package["Name"])
        if key in observed:
            raise GateError(f"duplicate dependency scan package {key}")
        observed[key] = package["Version"]
    for name, version in locked.items():
        if observed.get(name) != version:
            raise GateError(f"dependency scan lacks locked package {name}=={version}")
    if set(observed) != set(locked):
        raise GateError("dependency scan has unexpected packages outside the lock package set")
    artifact = f"{lock_path.name}@sha256:{digest(lock_path)}"
    accepted, lower = check_findings(report, artifact, kev, load_decisions(exceptions_path, now))
    return {"packages_checked": len(locked), "accepted_dispositions": accepted,
            "lower_severity_findings": lower, "blocking_findings": 0}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check an exact Python dependency lock")
    parser.add_argument("--require-hashes", action="store_true")
    parser.add_argument("--worker-inputs", action="store_true")
    parser.add_argument("lock", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.lock.name == DEV_LOCK_NAME:
            packages = validate_dev_inputs(args.lock)
        else:
            packages = validate_pip_lock(args.lock, require_hashes=args.require_hashes)
        if args.worker_inputs:
            if args.lock.resolve() != (Path.cwd() / WORKER_LOCK).resolve():
                raise GateError("worker input check requires the reviewed worker lock path")
            validate_worker_inputs(Path.cwd())
    except GateError as exc:
        print(f"dependency lock blocked: {exc}", file=sys.stderr)
        return 1
    print(f"validated {len(packages)} exact dependency pins in {args.lock}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
