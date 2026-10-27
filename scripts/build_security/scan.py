"""Produce and verify Trivy/KEV evidence for locks or release image digests.

The scanner runs without source credentials. Private registry access, if later
needed, belongs in an approved release environment, never a pull request.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from scripts.build_security.archive_inventory import capture_image_inventory
from scripts.build_security.gate import (
    DEV_LOCK_NAME,
    GateError,
    digest,
    validate_dependency_report,
    validate_dev_inputs,
    validate_kev,
    validate_manifest,
    validate_pip_lock,
    validate_release,
    validate_scanner_version,
)

KEV_URL = (
    "https://raw.githubusercontent.com/cisagov/kev-data/develop/"
    "known_exploited_vulnerabilities.json"
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def run_trivy(args: list[str], *, binary: str = "trivy") -> str:
    try:
        result = subprocess.run([binary, *args], capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise GateError("Trivy scanner unavailable") from exc
    if result.returncode:
        # Scan output can contain source locations; keep it out of ordinary CI logs.
        raise GateError(f"Trivy {' '.join(args[:2])} failed with exit {result.returncode}")
    return result.stdout


def fetch_kev(path: Path) -> datetime:
    request = urllib.request.Request(KEV_URL, headers={"User-Agent": "research-build-security/1"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read(8 * 1024 * 1024 + 1)
    except (OSError, urllib.error.URLError) as exc:
        raise GateError("KEV feed unavailable") from exc
    if len(payload) > 8 * 1024 * 1024:
        raise GateError("KEV feed exceeds configured size limit")
    try:
        parsed = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise GateError("invalid KEV feed JSON") from exc
    if not isinstance(parsed, dict):
        raise GateError("invalid KEV feed JSON")
    validate_kev(parsed)
    path.write_bytes(payload)
    return utc_now()


def prepare_output(path: Path) -> None:
    if path.exists() and any(path.iterdir()):
        raise GateError(f"evidence directory must be empty: {path}")
    path.mkdir(parents=True, exist_ok=True)


def prepare_scanner(output: Path) -> tuple[Path, Path, datetime]:
    run_trivy(["image", "--download-db-only"])
    version_path = output / "trivy-version.json"
    version_path.write_text(run_trivy(["version", "--format", "json"]), encoding="utf-8")
    try:
        version = json.loads(version_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GateError("invalid Trivy version JSON") from exc
    validate_scanner_version(version, utc_now())
    kev_path = output / "kev.json"
    fetched_at = fetch_kev(kev_path)
    return version_path, kev_path, fetched_at


def scan_dependencies(lock: Path, output: Path, exceptions: Path | None = None) -> dict[str, int]:
    if lock.name == DEV_LOCK_NAME:
        validate_dev_inputs(lock)
    else:
        validate_pip_lock(lock, require_hashes=lock.name == "requirements-worker.lock")
    prepare_output(output)
    version_path, kev_path, fetched_at = prepare_scanner(output)
    empty_ignore = output / "empty.trivyignore"
    empty_ignore.write_text("", encoding="utf-8")
    report = output / "dependencies.scan.json"
    with tempfile.TemporaryDirectory(prefix="dependency-scan-") as directory:
        context = Path(directory)
        shutil.copyfile(lock, context / "requirements.txt")
        run_trivy(["fs", "--scanners", "vuln", "--pkg-types", "library",
                   "--list-all-pkgs", "--skip-db-update", "--ignorefile", str(empty_ignore),
                   "--format", "json", "--output", str(report), str(context)])
    summary = validate_dependency_report(lock, report, version_path, kev_path,
                                         fetched_at.isoformat(), exceptions)
    (output / "decision.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def scan_release(
    manifest_path: Path,
    repository_root: Path,
    output: Path,
    exceptions: Path | None = None,
) -> dict[str, int]:
    manifest = validate_manifest(manifest_path, repository_root)
    prepare_output(output)
    version_path, kev_path, fetched_at = prepare_scanner(output)
    empty_ignore = output / "empty.trivyignore"
    empty_ignore.write_text("", encoding="utf-8")
    evidence: dict[str, object] = {
        "schema_version": 1,
        "manifest_sha256": digest(manifest_path),
        "locks": {lock: digest(repository_root / lock) for lock in manifest["dependency_locks"]},
        "trivy_version_file": version_path.name,
        "trivy_version_sha256": digest(version_path),
        "kev_file": kev_path.name,
        "kev_sha256": digest(kev_path),
        "kev_fetched_at": fetched_at.isoformat(),
        "images": [],
    }
    image_dir = output / "images"
    image_dir.mkdir()
    images: list[dict[str, object]] = []
    for role, ref in manifest["images"].items():
        platform = manifest["platforms"][role]
        scan_path = image_dir / f"{role}.scan.json"
        sbom_path = image_dir / f"{role}.sbom.cdx.json"
        archive_path = image_dir / f"{role}.archive-inventory.json"
        common = ["image", "--skip-db-update", "--platform", platform,
                  "--pkg-types", "os,library",
                  "--list-all-pkgs", "--ignorefile", str(empty_ignore)]
        run_trivy([*common, "--scanners", "vuln", "--format", "json",
                   "--output", str(scan_path), ref])
        run_trivy([*common, "--format", "cyclonedx", "--output", str(sbom_path), ref])
        archive_path.write_text(
            json.dumps(capture_image_inventory(ref, platform), indent=2) + "\n",
            encoding="utf-8",
        )
        images.append({
            "role": role,
            "ref": ref,
            "platform": platform,
            "scanned_at": utc_now().isoformat(),
            "scan_file": str(scan_path.relative_to(output)),
            "scan_sha256": digest(scan_path),
            "sbom_file": str(sbom_path.relative_to(output)),
            "sbom_sha256": digest(sbom_path),
            "archive_inventory_file": str(archive_path.relative_to(output)),
            "archive_inventory_sha256": digest(archive_path),
            "package_types": ["os", "library"],
        })
    evidence["images"] = images
    (output / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    summary = validate_release(manifest_path, output, repository_root, exceptions)
    (output / "decision.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    deps = sub.add_parser("dependencies", help="scan one exact pip lock in a clean context")
    deps.add_argument("--lock", type=Path, required=True)
    deps.add_argument("--output", type=Path, required=True)
    deps.add_argument("--exceptions", type=Path)
    release = sub.add_parser("release", help="scan exact release image digests and validate evidence")
    release.add_argument("--manifest", type=Path, required=True)
    release.add_argument("--repository-root", type=Path, default=Path("."))
    release.add_argument("--output", type=Path, required=True)
    release.add_argument("--exceptions", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "dependencies":
            summary = scan_dependencies(args.lock, args.output, args.exceptions)
        else:
            summary = scan_release(args.manifest, args.repository_root, args.output,
                                   args.exceptions)
    except GateError as exc:
        print(f"security gate blocked: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
