"""Behavior tests for promotion evidence and finding policy."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scripts.build_security.gate import (
    GateError,
    validate_dependency_report,
    validate_release,
)
from scripts.build_security.gate import main as gate_main

NOW = datetime(2026, 10, 26, 12, tzinfo=UTC)
ROLES = ("spike_worker", "openshell_gateway", "openshell_supervisor", "openshell_runtime")
WORKER_PINS = {
    "deepagents": "0.7.32",
    "langchain": "1.4.7",
    "langchain-core": "1.7.0",
    "langgraph": "1.2.17",
    "langchain-openai": "1.7.2",
}


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Fixture:
    def __init__(self, root):
        self.root = root
        self.lock = root / "spikes/full_graph/requirements-worker.lock"
        self.lock.parent.mkdir(parents=True)
        continuation = " " + chr(92) + "\n"
        self.lock.write_text(
            "".join(f"{name}=={version}{continuation}    --hash=sha256:{i:064x}\n"
                    for i, (name, version) in enumerate(WORKER_PINS.items(), 1)),
            encoding="utf-8",
        )
        self.direct = root / "spikes/full_graph/requirements-worker.txt"
        self.direct.write_text(
            "".join(f"{name}=={version}\n" for name, version in WORKER_PINS.items()),
            encoding="utf-8",
        )
        self.version_manifest = root / "spikes/full_graph/version-manifest.json"
        write(self.version_manifest, {
            **{name.replace("-", "_"): version for name, version in WORKER_PINS.items()},
            "python_minor": "3.13",
        })
        self.manifest = root / "manifest.json"
        self.refs = {role: f"example.org/{role}@sha256:{i:064x}" for i, role in enumerate(ROLES, 1)}
        self.platforms = {role: "linux/arm64" for role in ROLES}
        self.m = {"schema_version": 1, "profile": "spike", "uses_kubernetes": False,
                  "gcp_host_relay_enabled": False,
                  "dependency_locks": [str(self.lock.relative_to(root))], "images": self.refs,
                  "platforms": self.platforms}
        self.dir = root / "evidence"
        self.version = self.dir / "trivy-version.json"
        self.kev = self.dir / "kev.json"
        self.exceptions = root / "exceptions.json"
        write(self.version, {"Version": "0.76.1", "VulnerabilityDB": {
            "Version": 2, "UpdatedAt": (NOW - timedelta(hours=2)).isoformat(),
            "DownloadedAt": (NOW - timedelta(hours=1)).isoformat()}})
        write(self.kev, {"catalogVersion": "2026.10.26", "dateReleased": NOW.isoformat(),
                         "count": 1, "vulnerabilities": [{
                             "cveID": "CVE-2026-9999", "vendorProject": "Example",
                             "product": "Fixture", "vulnerabilityName": "Fixture vulnerability",
                             "dateAdded": "2026-10-20", "shortDescription": "Synthetic case",
                             "requiredAction": "Apply fixture update", "dueDate": "2026-11-10",
                             "knownRansomwareCampaignUse": "Unknown", "notes": "Synthetic only"}]})
        write(self.exceptions, {"schema_version": 1, "decisions": []})
        self.e = {"schema_version": 1, "locks": {}, "manifest_sha256": "",
                  "trivy_version_file": "trivy-version.json", "trivy_version_sha256": "",
                  "kev_file": "kev.json", "kev_sha256": "", "kev_fetched_at": NOW.isoformat(),
                  "images": []}
        for role, ref in self.refs.items():
            scan = f"images/{role}.scan.json"
            sbom = f"images/{role}.sbom.cdx.json"
            archive_inventory = f"images/{role}.archive-inventory.json"
            image_id = f"sha256:{(300 + len(self.e['images'])):064x}"
            # Trivy's CycloneDX root emits DiffID properties in sorted order,
            # while its scan metadata and Docker retain filesystem layer order.
            rootfs_diff_ids = [
                f"sha256:{(400 + len(self.e['images'])):064x}",
                f"sha256:{(399 + len(self.e['images'])):064x}",
            ]
            results = [{"Target": ref, "Class": "os-pkgs", "Type": "alpine",
                        "Packages": [{"Name": "busybox", "Version": "1.0",
                                      "Identifier": {"PURL": "pkg:apk/alpine/busybox@1.0"}}],
                        "Vulnerabilities": []}]
            if role == "spike_worker":
                results.append({"Target": "Python packages", "Class": "lang-pkgs",
                                "Type": "python-pkg", "Packages": [
                                    {"Name": name, "Version": version,
                                     "Identifier": {"PURL": f"pkg:pypi/{name}@{version}"}}
                                    for name, version in WORKER_PINS.items()],
                                "Vulnerabilities": []})
            else:
                results.append({"Target": role, "Class": "lang-pkgs",
                                "Type": "rustbinary", "Packages": [
                                    {"Name": "sample-lib", "Version": "1.0",
                                     "Identifier": {"PURL": "pkg:cargo/sample-lib@1.0"}}],
                                "Vulnerabilities": []})
            write(self.dir / scan, {"SchemaVersion": 2, "ArtifactName": ref,
                "ArtifactType": "container_image", "Metadata": {
                    "ImageID": image_id,
                    "DiffIDs": rootfs_diff_ids,
                    "ImageConfig": {
                        "os": "linux", "architecture": "arm64",
                        "rootfs": {"type": "layers", "diff_ids": rootfs_diff_ids},
                    }}, "Results": results})
            write(self.dir / sbom, {"bomFormat": "CycloneDX", "specVersion": "1.6",
                "metadata": {"component": {"type": "container", "name": ref,
                    "purl": f"pkg:oci/{role}@sha256:{ref.split('sha256:')[1]}?arch=arm64",
                    "properties": [
                        *({"name": "aquasecurity:trivy:DiffID", "value": layer}
                          for layer in sorted(rootfs_diff_ids)),
                        {"name": "aquasecurity:trivy:ImageID", "value": image_id},
                        {"name": "aquasecurity:trivy:Reference", "value": ref},
                    ]}},
                "components": [{"type": "library", "name": package["Name"],
                                "version": package["Version"],
                                "purl": package["Identifier"]["PURL"]}
                               for result in results for package in result["Packages"]]})
            write(self.dir / archive_inventory, {
                "schema_version": 2,
                "source": "docker-container-export",
                "ref": ref,
                "platform": "linux/arm64",
                "resolved_image_id": f"sha256:{(100 + len(self.e['images'])):064x}",
                "resolved_descriptor_digest": f"sha256:{(200 + len(self.e['images'])):064x}",
                "container_image_id": image_id,
                "rootfs_diff_ids": rootfs_diff_ids,
                "observed_os": "linux",
                "observed_architecture": "arm64",
                "captured_at": NOW.isoformat(),
                "export_sha256": f"{(200 + len(self.e['images'])):064x}",
                "export_bytes": 10240,
                "entries_seen": 2,
                "regular_files_seen": 1,
                "complete": True,
                "candidates": [],
            })
            self.e["images"].append({"role": role, "ref": ref, "platform": "linux/arm64",
                "scanned_at": NOW.isoformat(),
                "scan_file": scan, "scan_sha256": "", "sbom_file": sbom,
                "sbom_sha256": "", "archive_inventory_file": archive_inventory,
                "archive_inventory_sha256": "", "package_types": ["os", "library"]})
        self.save()

    def save(self):
        write(self.manifest, self.m)
        self.e["manifest_sha256"] = sha(self.manifest)
        self.e["locks"] = {str(self.lock.relative_to(self.root)): sha(self.lock) if self.lock.exists() else "0" * 64}
        self.e["trivy_version_sha256"] = sha(self.version)
        self.e["kev_sha256"] = sha(self.kev)
        for x in self.e["images"]:
            if (self.dir / x["scan_file"]).exists():
                x["scan_sha256"] = sha(self.dir / x["scan_file"])
            if (self.dir / x["sbom_file"]).exists():
                x["sbom_sha256"] = sha(self.dir / x["sbom_file"])
            if x.get("archive_inventory_file") and (self.dir / x["archive_inventory_file"]).exists():
                x["archive_inventory_sha256"] = sha(self.dir / x["archive_inventory_file"])
        write(self.dir / "evidence.json", self.e)

    def archive_inventory(self, role="spike_worker"):
        path = self.dir / f"images/{role}.archive-inventory.json"
        return path, json.loads(path.read_text(encoding="utf-8"))

    def check(self):
        return validate_release(self.manifest, self.dir, self.root, self.exceptions, NOW)

    def finding(self, severity="HIGH", cve="CVE-2026-1234", aliases=None):
        path = self.dir / "images/spike_worker.scan.json"
        report = json.loads(path.read_text(encoding="utf-8"))
        report["Results"][0]["Vulnerabilities"] = [{"VulnerabilityID": cve,
            "VendorIDs": aliases or [], "Severity": severity, "PkgName": "busybox",
            "InstalledVersion": "1.0"}]
        write(path, report)
        self.save()

    def exception(self, *, artifact=None, platform="linux/arm64", expires_at=None):
        write(self.exceptions, {"schema_version": 1, "decisions": [{
            "artifact": artifact or self.refs["spike_worker"],
            "platform": platform,
            "vulnerability_id": "CVE-2026-1234", "package": "busybox",
            "installed_version": "1.0", "decision": "temporary_exception",
            "security_owner": "security-reviewer@example.org", "ticket": "SEC-123",
            "reason": "Short mitigation window", "vendor_evidence":
            "https://vendor.example.org/advisory/CVE-2026-1234",
            "mitigation": "Bounded use", "approved_at": NOW.isoformat(),
            "expires_at": (expires_at or NOW + timedelta(days=7)).isoformat()}]})

    def triage(self, *, owner="worker-owner@example.org", due_at=None,
               artifact=None, platform="linux/arm64"):
        write(self.exceptions, {"schema_version": 1, "decisions": [{
            "artifact": artifact or self.refs["spike_worker"],
            "platform": platform,
            "vulnerability_id": "CVE-2026-1234", "package": "busybox",
            "installed_version": "1.0", "decision": "triage",
            "owner": owner, "ticket": "SEC-456", "reason": "Patch queued",
            "due_at": (due_at or NOW + timedelta(days=14)).isoformat()}]})


class ReleaseGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.f = Fixture(Path(self.tmp.name))

    def test_complete_clean_evidence_passes(self):
        self.assertEqual(self.f.check()["images_checked"], 4)

    def test_observed_trivy_sbom_root_shape_passes_with_sorted_diffids(self):
        sbom_path = self.f.dir / "images/spike_worker.sbom.cdx.json"
        sbom = json.loads(sbom_path.read_text(encoding="utf-8"))
        scan_path = self.f.dir / "images/spike_worker.scan.json"
        scan = json.loads(scan_path.read_text(encoding="utf-8"))
        props = sbom["metadata"]["component"]["properties"]
        sbom_diff_ids = [p["value"] for p in props if p["name"] == "aquasecurity:trivy:DiffID"]
        self.assertEqual(sbom_diff_ids, sorted(scan["Metadata"]["DiffIDs"]))
        self.assertNotEqual(sbom_diff_ids, scan["Metadata"]["DiffIDs"])
        self.assertEqual(self.f.check()["images_checked"], 4)

    def test_missing_sbom_root_identity_properties_block_with_updated_checksum(self):
        path = self.f.dir / "images/spike_worker.sbom.cdx.json"
        original = json.loads(path.read_text(encoding="utf-8"))
        properties = original["metadata"]["component"]["properties"]
        changes = {
            "all": None,
            "image_id": [p for p in properties if p["name"] != "aquasecurity:trivy:ImageID"],
            "diff_ids": [p for p in properties if p["name"] != "aquasecurity:trivy:DiffID"],
        }
        for missing, updated in changes.items():
            with self.subTest(missing=missing):
                sbom = json.loads(json.dumps(original))
                if updated is None:
                    sbom["metadata"]["component"].pop("properties")
                else:
                    sbom["metadata"]["component"]["properties"] = updated
                write(path, sbom)
                self.f.save()
                with self.assertRaisesRegex(GateError, "SBOM.*(ImageID|DiffID|properties)"):
                    self.f.check()

    def test_wrong_sbom_root_identity_blocks_with_updated_checksum(self):
        path = self.f.dir / "images/spike_worker.sbom.cdx.json"
        original = json.loads(path.read_text(encoding="utf-8"))
        for name in ("aquasecurity:trivy:ImageID", "aquasecurity:trivy:DiffID"):
            with self.subTest(name=name):
                sbom = json.loads(json.dumps(original))
                for prop in sbom["metadata"]["component"]["properties"]:
                    if prop["name"] == name:
                        prop["value"] = "sha256:" + "a" * 64
                        break
                write(path, sbom)
                self.f.save()
                with self.assertRaisesRegex(GateError, "SBOM.*(ImageID|DiffID)"):
                    self.f.check()

    def test_malformed_or_extra_sbom_root_properties_block_with_updated_checksum(self):
        path = self.f.dir / "images/spike_worker.sbom.cdx.json"
        original = json.loads(path.read_text(encoding="utf-8"))
        properties = original["metadata"]["component"]["properties"]
        image_id = next(p for p in properties if p["name"] == "aquasecurity:trivy:ImageID")
        diff_id = next(p for p in properties if p["name"] == "aquasecurity:trivy:DiffID")
        changes = {
            "non_list": "not-a-list",
            "malformed_entry": [*properties, {"name": "aquasecurity:trivy:DiffID"}],
            "malformed_image_id": [
                {**p, "value": "sha256:short"} if p is image_id else p for p in properties
            ],
            "malformed_diff_id": [
                {**p, "value": 12} if p is diff_id else p for p in properties
            ],
            "duplicate_image_id": [*properties, dict(image_id)],
            "duplicate_diff_id": [*properties, dict(diff_id)],
            "extra_diff_id": [*properties, {
                "name": "aquasecurity:trivy:DiffID", "value": "sha256:" + "b" * 64,
            }],
        }
        for condition, updated in changes.items():
            with self.subTest(condition=condition):
                sbom = json.loads(json.dumps(original))
                sbom["metadata"]["component"]["properties"] = updated
                write(path, sbom)
                self.f.save()
                with self.assertRaisesRegex(GateError, "SBOM.*(ImageID|DiffID|properties)"):
                    self.f.check()

    def test_trivy_image_id_mismatch_with_checksums_blocks_release(self):
        scan_path = self.f.dir / "images/spike_worker.scan.json"
        report = json.loads(scan_path.read_text(encoding="utf-8"))
        report["Metadata"]["ImageID"] = "sha256:" + "a" * 64
        write(scan_path, report)
        self.f.save()
        with self.assertRaisesRegex(GateError, "image identity|ImageID"):
            self.f.check()

    def test_trivy_rootfs_diff_ids_mismatch_with_checksums_blocks_release(self):
        scan_path = self.f.dir / "images/spike_worker.scan.json"
        report = json.loads(scan_path.read_text(encoding="utf-8"))
        report["Metadata"]["DiffIDs"] = ["sha256:" + "a" * 64]
        report["Metadata"]["ImageConfig"]["rootfs"] = {
            "type": "layers", "diff_ids": ["sha256:" + "a" * 64],
        }
        write(scan_path, report)
        self.f.save()
        with self.assertRaisesRegex(GateError, "rootfs|image identity"):
            self.f.check()

    def test_trivy_metadata_and_image_config_rootfs_must_agree(self):
        scan_path = self.f.dir / "images/spike_worker.scan.json"
        report = json.loads(scan_path.read_text(encoding="utf-8"))
        report["Metadata"]["ImageConfig"]["rootfs"]["diff_ids"] = ["sha256:" + "f" * 64]
        write(scan_path, report)
        self.f.save()
        with self.assertRaisesRegex(GateError, "rootfs identity"):
            self.f.check()

    def test_missing_trivy_image_id_blocks_release(self):
        scan_path = self.f.dir / "images/spike_worker.scan.json"
        report = json.loads(scan_path.read_text(encoding="utf-8"))
        report["Metadata"].pop("ImageID")
        write(scan_path, report)
        self.f.save()
        with self.assertRaisesRegex(GateError, "image identity"):
            self.f.check()

    def test_old_inventory_schema_blocks_release(self):
        path, inventory = self.f.archive_inventory()
        inventory["schema_version"] = 1
        write(path, inventory)
        self.f.save()
        with self.assertRaisesRegex(GateError, "archive inventory.*schema"):
            self.f.check()

    def test_unpacked_vendor_file_candidate_blocks_release(self):
        path, inventory = self.f.archive_inventory()
        inventory["candidates"] = [{
            "path": "/usr/local/lib/python3.13/site-packages/sample/_vendor/lib/__init__.py",
            "kind": "regular", "reason": "vendored_file", "size": 12,
            "sha256": "a" * 64,
        }]
        write(path, inventory)
        self.f.save()
        with self.assertRaisesRegex(GateError, "unexamined archive candidate"):
            self.f.check()

    def test_missing_archive_inventory_blocks_even_when_scan_and_sbom_match(self):
        self.f.e["images"][0].pop("archive_inventory_file")
        self.f.e["images"][0].pop("archive_inventory_sha256")
        self.f.save()
        with self.assertRaisesRegex(GateError, "archive inventory"):
            self.f.check()

    def test_missing_or_tampered_archive_inventory_file_blocks(self):
        path, _ = self.f.archive_inventory()
        path.unlink()
        with self.assertRaisesRegex(GateError, "archive inventory"):
            self.f.check()

    def test_nested_ensurepip_wheel_blocks_even_when_scan_and_sbom_match(self):
        path, inventory = self.f.archive_inventory()
        inventory["candidates"] = [{
            "path": "/usr/local/lib/python3.13/ensurepip/_bundled/pip-25.2-py3-none-any.whl",
            "kind": "regular", "reason": "archive_name", "size": 100,
            "sha256": "a" * 64,
        }]
        write(path, inventory)
        self.f.save()
        with self.assertRaisesRegex(GateError, "unexamined archive|archive candidate"):
            self.f.check()

    def test_vendored_manifest_blocks_but_ordinary_dist_info_does_not(self):
        path, inventory = self.f.archive_inventory()
        inventory["candidates"] = [{
            "path": "/usr/local/lib/python3.13/site-packages/sample/_vendor/thing/package.json",
            "kind": "regular", "reason": "vendored_manifest", "size": 100,
            "sha256": "b" * 64,
        }]
        write(path, inventory)
        self.f.save()
        with self.assertRaisesRegex(GateError, "unexamined archive|archive candidate"):
            self.f.check()

    def test_archive_inventory_wrong_ref_platform_or_observed_image_blocks(self):
        path, original = self.f.archive_inventory()
        changes = (
            ("ref", self.f.refs["openshell_gateway"]),
            ("platform", "linux/amd64"),
            ("observed_architecture", "amd64"),
            ("resolved_image_id", "not-a-digest"),
            ("resolved_descriptor_digest", "not-a-digest"),
            ("container_image_id", "not-a-digest"),
        )
        for key, value in changes:
            with self.subTest(key=key):
                inventory = {**original, key: value}
                write(path, inventory)
                self.f.save()
                with self.assertRaisesRegex(GateError, "archive inventory"):
                    self.f.check()

    def test_archive_inventory_incomplete_stale_or_empty_blocks(self):
        path, original = self.f.archive_inventory()
        changes = (
            ("complete", False),
            ("captured_at", (NOW - timedelta(days=3)).isoformat()),
            ("export_bytes", 0),
            ("entries_seen", 0),
            ("regular_files_seen", 0),
        )
        for key, value in changes:
            with self.subTest(key=key):
                inventory = {**original, key: value}
                write(path, inventory)
                self.f.save()
                with self.assertRaisesRegex(GateError, "archive inventory"):
                    self.f.check()

    def test_archive_inventory_candidate_path_and_type_must_be_safe(self):
        path, original = self.f.archive_inventory()
        bad_candidates = (
            {"path": "/usr/local/../tmp/pip.whl", "kind": "regular", "reason": "archive_name",
             "size": 100, "sha256": "a" * 64},
            {"path": "/usr/local/pip.whl", "kind": "directory", "reason": "archive_name",
             "size": 0, "sha256": None},
        )
        for candidate in bad_candidates:
            with self.subTest(candidate=candidate):
                write(path, {**original, "candidates": [candidate]})
                self.f.save()
                with self.assertRaisesRegex(GateError, "archive inventory"):
                    self.f.check()

    def test_falsy_nonlist_vulnerabilities_block_with_updated_checksum(self):
        path = self.f.dir / "images/spike_worker.scan.json"
        for malformed in ("", False, {}, {"not_a_list": []}, 0):
            with self.subTest(malformed=malformed):
                report = json.loads(path.read_text(encoding="utf-8"))
                report["Results"][0]["Vulnerabilities"] = malformed
                write(path, report)
                self.f.save()
                with self.assertRaisesRegex(GateError, "invalid scan vulnerabilities"):
                    self.f.check()

    def test_null_or_absent_vulnerabilities_are_clean_trivy_shapes(self):
        path = self.f.dir / "images/spike_worker.scan.json"
        for mode in ("null", "absent"):
            with self.subTest(mode=mode):
                report = json.loads(path.read_text(encoding="utf-8"))
                if mode == "null":
                    report["Results"][0]["Vulnerabilities"] = None
                else:
                    report["Results"][0].pop("Vulnerabilities", None)
                write(path, report)
                self.f.save()
                self.assertEqual(self.f.check()["images_checked"], 4)

    def test_falsy_nonlist_vendor_ids_block_with_updated_checksum(self):
        self.f.finding()
        self.f.exception()
        path = self.f.dir / "images/spike_worker.scan.json"
        for malformed in ("", False, {}, {"not_a_list": []}, 0, [""]):
            with self.subTest(malformed=malformed):
                report = json.loads(path.read_text(encoding="utf-8"))
                report["Results"][0]["Vulnerabilities"][0]["VendorIDs"] = malformed
                write(path, report)
                self.f.save()
                with self.assertRaisesRegex(GateError, "VendorIDs|vulnerability finding"):
                    self.f.check()

    def test_null_or_absent_vendor_ids_keep_primary_finding(self):
        self.f.finding()
        self.f.exception()
        path = self.f.dir / "images/spike_worker.scan.json"
        for mode in ("null", "absent"):
            with self.subTest(mode=mode):
                report = json.loads(path.read_text(encoding="utf-8"))
                finding = report["Results"][0]["Vulnerabilities"][0]
                if mode == "null":
                    finding["VendorIDs"] = None
                else:
                    finding.pop("VendorIDs", None)
                write(path, report)
                self.f.save()
                self.assertEqual(self.f.check()["accepted_dispositions"], 1)

    def test_missing_lock_blocks(self):
        self.f.lock.unlink()
        with self.assertRaisesRegex(GateError, "lock"):
            self.f.check()

    def test_unpinned_lock_blocks(self):
        self.f.lock.write_text("jsonschema>=4.25\n", encoding="utf-8")
        self.f.save()
        with self.assertRaisesRegex(GateError, "pin"):
            self.f.check()

    def test_unhashed_worker_lock_blocks_promotion(self):
        self.f.lock.write_text(
            "".join(f"{name}=={version}\n" for name, version in WORKER_PINS.items()),
            encoding="utf-8",
        )
        self.f.save()
        with self.assertRaisesRegex(GateError, "hash"):
            self.f.check()

    def test_missing_digest_blocks(self):
        self.f.m["images"]["spike_worker"] = "example.org/spike_worker:latest"
        self.f.save()
        with self.assertRaisesRegex(GateError, "digest"):
            self.f.check()

    def test_missing_platform_blocks(self):
        del self.f.m["platforms"]["spike_worker"]
        self.f.save()
        with self.assertRaisesRegex(GateError, "platform"):
            self.f.check()

    def test_worker_platform_must_match_resolved_lock_target(self):
        self.f.m["platforms"]["spike_worker"] = "linux/amd64"
        self.f.save()
        with self.assertRaisesRegex(GateError, "worker.*platform"):
            self.f.check()

    def test_wrong_architecture_scan_blocks(self):
        path = self.f.dir / "images/spike_worker.scan.json"
        report = json.loads(path.read_text(encoding="utf-8"))
        report["Metadata"]["ImageConfig"]["architecture"] = "amd64"
        write(path, report)
        self.f.save()
        with self.assertRaisesRegex(GateError, "platform"):
            self.f.check()

    def test_wrong_architecture_sbom_blocks(self):
        path = self.f.dir / "images/spike_worker.sbom.cdx.json"
        sbom = json.loads(path.read_text(encoding="utf-8"))
        sbom["metadata"]["component"]["purl"] = sbom["metadata"]["component"]["purl"].replace(
            "arch=arm64", "arch=amd64")
        write(path, sbom)
        self.f.save()
        with self.assertRaisesRegex(GateError, "SBOM.*platform"):
            self.f.check()

    def test_unscanned_runtime_role_blocks(self):
        del self.f.m["images"]["openshell_runtime"]
        self.f.save()
        with self.assertRaisesRegex(GateError, "openshell_runtime"):
            self.f.check()

    def test_missing_sbom_blocks(self):
        (self.f.dir / "images/spike_worker.sbom.cdx.json").unlink()
        with self.assertRaisesRegex(GateError, "SBOM"):
            self.f.check()

    def test_missing_scan_blocks(self):
        (self.f.dir / "images/spike_worker.scan.json").unlink()
        with self.assertRaisesRegex(GateError, "scan"):
            self.f.check()

    def test_stale_advisory_database_blocks(self):
        v = json.loads(self.f.version.read_text(encoding="utf-8"))
        v["VulnerabilityDB"]["UpdatedAt"] = (NOW - timedelta(days=4)).isoformat()
        write(self.f.version, v)
        self.f.save()
        with self.assertRaisesRegex(GateError, "database.*stale"):
            self.f.check()

    def test_stale_scan_blocks(self):
        self.f.e["images"][0]["scanned_at"] = (NOW - timedelta(days=3)).isoformat()
        self.f.save()
        with self.assertRaisesRegex(GateError, "scan.*stale"):
            self.f.check()

    def test_high_finding_blocks(self):
        self.f.finding()
        with self.assertRaisesRegex(GateError, "CVE-2026-1234"):
            self.f.check()

    def test_kev_alias_blocks_at_medium(self):
        self.f.finding("MEDIUM", "GHSA-test", ["CVE-2026-9999"])
        with self.assertRaisesRegex(GateError, "CVE-2026-9999"):
            self.f.check()

    def test_missing_coverage_blocks(self):
        path = self.f.dir / "images/spike_worker.scan.json"
        report = json.loads(path.read_text(encoding="utf-8"))
        report["Results"] = []
        write(path, report)
        self.f.save()
        with self.assertRaisesRegex(GateError, "coverage"):
            self.f.check()

    def test_worker_image_missing_locked_python_package_blocks(self):
        path = self.f.dir / "images/spike_worker.scan.json"
        report = json.loads(path.read_text(encoding="utf-8"))
        report["Results"][1]["Packages"].pop()
        write(path, report)
        self.f.save()
        with self.assertRaisesRegex(GateError, "worker.*langchain-openai"):
            self.f.check()

    def test_scanned_vendored_copy_does_not_hide_locked_version(self):
        path = self.f.dir / "images/spike_worker.scan.json"
        report = json.loads(path.read_text(encoding="utf-8"))
        report["Results"][1]["Packages"].append({
            "Name": "langchain-openai", "Version": "1.7.1",
            "Identifier": {"PURL": "pkg:pypi/langchain-openai@1.7.1"},
        })
        write(path, report)
        sbom_path = self.f.dir / "images/spike_worker.sbom.cdx.json"
        sbom = json.loads(sbom_path.read_text(encoding="utf-8"))
        sbom["components"].append({"type": "library", "name": "langchain-openai",
                                   "version": "1.7.1",
                                   "purl": "pkg:pypi/langchain-openai@1.7.1"})
        write(sbom_path, sbom)
        self.f.save()
        self.assertEqual(self.f.check()["images_checked"], 4)

    def test_tampered_scan_blocks(self):
        path = self.f.dir / "images/spike_worker.scan.json"
        path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        with self.assertRaisesRegex(GateError, "checksum"):
            self.f.check()

    def test_sbom_for_other_digest_blocks(self):
        path = self.f.dir / "images/spike_worker.sbom.cdx.json"
        sbom = json.loads(path.read_text(encoding="utf-8"))
        sbom["metadata"]["component"]["name"] = self.f.refs["openshell_gateway"]
        write(path, sbom)
        self.f.save()
        with self.assertRaisesRegex(GateError, "SBOM.*digest"):
            self.f.check()

    def test_exact_scoped_exception_passes(self):
        self.f.finding()
        self.f.exception()
        self.assertEqual(self.f.check()["accepted_dispositions"], 1)

    def test_other_digest_exception_does_not_apply(self):
        self.f.finding()
        self.f.exception(artifact=self.f.refs["openshell_gateway"])
        with self.assertRaisesRegex(GateError, "CVE-2026-1234"):
            self.f.check()

    def test_other_platform_exception_does_not_apply(self):
        self.f.finding()
        self.f.exception(platform="linux/amd64")
        with self.assertRaisesRegex(GateError, "CVE-2026-1234"):
            self.f.check()

    def test_expired_exception_does_not_apply(self):
        self.f.finding()
        self.f.exception(expires_at=NOW - timedelta(days=1))
        with self.assertRaisesRegex(GateError, "CVE-2026-1234"):
            self.f.check()

    def test_missing_kev_feed_blocks(self):
        self.f.kev.unlink()
        with self.assertRaisesRegex(GateError, "KEV"):
            self.f.check()

    def test_missing_os_inventory_blocks_despite_scanner_option_claim(self):
        path = self.f.dir / "images/openshell_runtime.scan.json"
        report = json.loads(path.read_text(encoding="utf-8"))
        report["Results"] = [result for result in report["Results"]
                             if result["Class"] != "os-pkgs"]
        write(path, report)
        self.f.save()
        with self.assertRaisesRegex(GateError, "OS.*coverage|os-pkgs"):
            self.f.check()

    def test_missing_language_inventory_blocks_despite_scanner_option_claim(self):
        path = self.f.dir / "images/openshell_gateway.scan.json"
        report = json.loads(path.read_text(encoding="utf-8"))
        report["Results"] = [result for result in report["Results"]
                             if result["Class"] != "lang-pkgs"]
        write(path, report)
        self.f.save()
        with self.assertRaisesRegex(GateError, "language.*coverage|lang-pkgs"):
            self.f.check()

    def test_sbom_missing_scanned_worker_package_blocks(self):
        path = self.f.dir / "images/spike_worker.sbom.cdx.json"
        sbom = json.loads(path.read_text(encoding="utf-8"))
        sbom["components"] = [item for item in sbom["components"]
                              if item.get("name") != "langchain-openai"]
        write(path, sbom)
        self.f.save()
        with self.assertRaisesRegex(GateError, "SBOM.*inventory|SBOM.*package"):
            self.f.check()

    def test_sbom_duplicate_package_purl_blocks_multiset_mismatch(self):
        path = self.f.dir / "images/spike_worker.sbom.cdx.json"
        sbom = json.loads(path.read_text(encoding="utf-8"))
        sbom["components"].append(dict(sbom["components"][-1]))
        write(path, sbom)
        self.f.save()
        with self.assertRaisesRegex(GateError, "SBOM.*inventory|SBOM.*package"):
            self.f.check()

    def test_sbom_wrong_oci_purl_digest_blocks_even_when_name_matches(self):
        path = self.f.dir / "images/spike_worker.sbom.cdx.json"
        sbom = json.loads(path.read_text(encoding="utf-8"))
        sbom["metadata"]["component"]["purl"] = re.sub(
            r"@sha256:[a-f0-9]{64}", "@sha256:" + "f" * 64,
            sbom["metadata"]["component"]["purl"],
        )
        write(path, sbom)
        self.f.save()
        with self.assertRaisesRegex(GateError, "SBOM.*digest"):
            self.f.check()

    def test_truncated_kev_declared_count_blocks(self):
        kev = json.loads(self.f.kev.read_text(encoding="utf-8"))
        kev["count"] = 1756
        write(self.f.kev, kev)
        self.f.save()
        with self.assertRaisesRegex(GateError, "KEV.*count"):
            self.f.check()

    def test_missing_kev_declared_count_blocks(self):
        kev = json.loads(self.f.kev.read_text(encoding="utf-8"))
        del kev["count"]
        write(self.f.kev, kev)
        self.f.save()
        with self.assertRaisesRegex(GateError, "KEV.*count"):
            self.f.check()

    def test_duplicate_kev_cve_blocks(self):
        kev = json.loads(self.f.kev.read_text(encoding="utf-8"))
        kev["count"] = 2
        kev["vulnerabilities"].append(dict(kev["vulnerabilities"][0]))
        write(self.f.kev, kev)
        self.f.save()
        with self.assertRaisesRegex(GateError, "duplicate.*KEV|KEV.*duplicate"):
            self.f.check()

    def test_incomplete_kev_entry_blocks(self):
        kev = json.loads(self.f.kev.read_text(encoding="utf-8"))
        del kev["vulnerabilities"][0]["vendorProject"]
        write(self.f.kev, kev)
        self.f.save()
        with self.assertRaisesRegex(GateError, "incomplete KEV"):
            self.f.check()

    def test_medium_finding_without_owner_and_due_blocks(self):
        self.f.finding("MEDIUM")
        with self.assertRaisesRegex(GateError, "CVE-2026-1234|triage"):
            self.f.check()

    def test_medium_finding_with_scoped_owner_and_due_passes(self):
        self.f.finding("MEDIUM")
        self.f.triage()
        self.assertEqual(self.f.check()["lower_severity_findings"], 1)

    def test_medium_finding_with_missing_owner_blocks(self):
        self.f.finding("MEDIUM")
        self.f.triage(owner="")
        with self.assertRaisesRegex(GateError, "owner|triage"):
            self.f.check()

    def test_medium_finding_with_past_due_date_blocks(self):
        self.f.finding("MEDIUM")
        self.f.triage(due_at=NOW - timedelta(days=1))
        with self.assertRaisesRegex(GateError, "due|expired"):
            self.f.check()

    def test_high_finding_cannot_use_triage(self):
        self.f.finding("HIGH")
        self.f.triage()
        with self.assertRaisesRegex(GateError, "CVE-2026-1234|HIGH"):
            self.f.check()

    def test_worker_direct_pin_drift_blocks(self):
        self.f.direct.write_text(
            self.f.direct.read_text(encoding="utf-8").replace("deepagents==0.7.32",
                                                              "deepagents==0.7.31"),
            encoding="utf-8",
        )
        self.f.save()
        with self.assertRaisesRegex(GateError, "direct.*lock|pin.*lock"):
            self.f.check()

    def test_worker_version_manifest_drift_blocks(self):
        versions = json.loads(self.f.version_manifest.read_text(encoding="utf-8"))
        versions["langgraph"] = "1.2.16"
        write(self.f.version_manifest, versions)
        self.f.save()
        with self.assertRaisesRegex(GateError, "version manifest.*lock"):
            self.f.check()

    def test_worker_version_manifest_missing_python_target_blocks(self):
        versions = json.loads(self.f.version_manifest.read_text(encoding="utf-8"))
        del versions["python_minor"]
        write(self.f.version_manifest, versions)
        self.f.save()
        with self.assertRaisesRegex(GateError, "Python target.*lock"):
            self.f.check()

    def test_unqualified_gcp_host_relay_is_disabled(self):
        self.f.m["gcp_host_relay_enabled"] = True
        self.f.save()
        with self.assertRaisesRegex(GateError, "GCP.*relay|relay.*GCP"):
            self.f.check()

    def test_missing_gcp_host_relay_disable_flag_blocks(self):
        del self.f.m["gcp_host_relay_enabled"]
        self.f.save()
        with self.assertRaisesRegex(GateError, "GCP.*relay|relay.*GCP"):
            self.f.check()


class DependencyGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.f = Fixture(Path(self.tmp.name))
        self.report = self.f.dir / "dependencies.scan.json"
        write(self.report, {"SchemaVersion": 2, "ArtifactType": "filesystem",
            "Results": [{"Target": "requirements.txt", "Class": "lang-pkgs", "Type": "pip",
            "Packages": [{"Name": name, "Version": version}
                         for name, version in WORKER_PINS.items()],
            "Vulnerabilities": []}]})

    def check(self):
        return validate_dependency_report(self.f.lock, self.report, self.f.version,
                                          self.f.kev, NOW.isoformat(), self.f.exceptions, NOW)

    def test_exact_locked_packages_are_scanned(self):
        self.assertEqual(self.check()["packages_checked"], len(WORKER_PINS))

    def test_falsy_nonlist_dependency_vulnerabilities_block(self):
        for malformed in ("", False, {}, {"not_a_list": []}, 0):
            with self.subTest(malformed=malformed):
                report = json.loads(self.report.read_text(encoding="utf-8"))
                report["Results"][0]["Vulnerabilities"] = malformed
                write(self.report, report)
                with self.assertRaisesRegex(GateError, "invalid scan vulnerabilities"):
                    self.check()

    def test_missing_scanned_package_blocks(self):
        report = json.loads(self.report.read_text(encoding="utf-8"))
        report["Results"][0]["Packages"].pop()
        write(self.report, report)
        with self.assertRaisesRegex(GateError, "langchain-openai"):
            self.check()

    def test_raw_lock_filename_zero_package_scan_blocks(self):
        write(self.report, {"SchemaVersion": 2, "ArtifactType": "filesystem", "Results": []})
        with self.assertRaisesRegex(GateError, "coverage"):
            self.check()

    def test_high_dependency_finding_blocks(self):
        report = json.loads(self.report.read_text(encoding="utf-8"))
        report["Results"][0]["Vulnerabilities"] = [{"VulnerabilityID": "CVE-2026-1234",
            "Severity": "HIGH", "PkgName": "deepagents", "InstalledVersion": "0.7.32"}]
        write(self.report, report)
        with self.assertRaisesRegex(GateError, "CVE-2026-1234"):
            self.check()

    def test_unhashed_worker_lock_blocks_dependency_gate(self):
        self.f.lock.write_text(
            "".join(f"{name}=={version}\n" for name, version in WORKER_PINS.items()),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(GateError, "hash"):
            self.check()

    def test_wrong_ecosystem_cannot_satisfy_pip_lock(self):
        report = json.loads(self.report.read_text(encoding="utf-8"))
        report["Results"][0].update({"Class": "os-pkgs", "Type": "alpine"})
        write(self.report, report)
        with self.assertRaisesRegex(GateError, "pip|ecosystem"):
            self.check()

    def test_wrong_target_cannot_satisfy_pip_lock(self):
        report = json.loads(self.report.read_text(encoding="utf-8"))
        report["Results"][0]["Target"] = "not-the-lock"
        write(self.report, report)
        with self.assertRaisesRegex(GateError, "requirements.txt|target"):
            self.check()

    def test_extra_scanned_package_blocks_coverage(self):
        report = json.loads(self.report.read_text(encoding="utf-8"))
        report["Results"][0]["Packages"].append({"Name": "surprise", "Version": "1.0"})
        write(self.report, report)
        with self.assertRaisesRegex(GateError, "package.*set|unexpected"):
            self.check()


class WorkflowGuardTests(unittest.TestCase):
    def test_tag_named_like_default_branch_cannot_run_release(self):
        workflow = (Path(__file__).resolve().parents[2] /
                    ".github/workflows/release-security.yml").read_text(encoding="utf-8")
        guard = re.search(r"^\s*run: (test .*DEFAULT_BRANCH.*)$", workflow, re.MULTILINE)
        self.assertIsNotNone(guard)
        env = os.environ.copy()
        env.update({"DEFAULT_BRANCH": "main", "GITHUB_REF": "refs/tags/main",
                    "GITHUB_REF_NAME": "main"})
        result = subprocess.run(["bash", "-c", guard.group(1)], env=env, check=False)
        self.assertNotEqual(result.returncode, 0)


class DevelopmentLockManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.lock = root / "requirements-dev.lock"
        self.direct = root / "requirements-dev.txt"
        self.lock.write_text(
            "jsonschema==4.25.1\nPyYAML==6.0.3\nhttpx==0.28.1\n", encoding="utf-8"
        )
        self.direct.write_text(
            "jsonschema>=4.25,<5\nPyYAML>=6.0,<7\nhttpx>=0.28.1,<0.29\n",
            encoding="utf-8",
        )

    def check(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return gate_main([str(self.lock)])

    def test_current_ranged_manifest_matches_pins(self):
        self.assertEqual(self.check(), 0)

    def test_new_direct_dependency_without_lock_pin_blocks(self):
        with self.direct.open("a", encoding="utf-8") as stream:
            stream.write("requests>=2.34,<3\n")
        self.assertEqual(self.check(), 1)

    def test_raised_direct_lower_bound_with_unchanged_lock_blocks(self):
        self.direct.write_text(
            self.direct.read_text(encoding="utf-8").replace(
                "jsonschema>=4.25,<5", "jsonschema>=4.26,<5"
            ),
            encoding="utf-8",
        )
        self.assertEqual(self.check(), 1)

    def test_lowered_direct_upper_bound_with_unchanged_lock_blocks(self):
        self.direct.write_text(
            self.direct.read_text(encoding="utf-8").replace(
                "httpx>=0.28.1,<0.29", "httpx>=0.28.1,<0.28.1"
            ),
            encoding="utf-8",
        )
        self.assertEqual(self.check(), 1)

    def test_missing_or_unsupported_direct_manifest_blocks(self):
        self.direct.unlink()
        self.assertEqual(self.check(), 1)
        self.direct.write_text("httpx~=0.28\n", encoding="utf-8")
        self.assertEqual(self.check(), 1)


if __name__ == "__main__":
    unittest.main()
