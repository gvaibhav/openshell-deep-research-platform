"""Scanner orchestration tests use a fake CLI and public fixture data only."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from scripts.build_security import scan
from scripts.build_security.gate import GateError
from scripts.build_security.test_gate import WORKER_PINS, Fixture, write


class ScannerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.fixture = Fixture(self.root)
        self.calls = []
        self.inventory_calls = []

    def fake_trivy(self, args, *, binary="trivy"):
        self.calls.append(args)
        now = datetime.now(UTC)
        if args[:2] == ["image", "--download-db-only"]:
            return ""
        if args[:3] == ["version", "--format", "json"]:
            return json.dumps({"Version": "0.76.1", "VulnerabilityDB": {
                "Version": 2, "UpdatedAt": (now - timedelta(hours=2)).isoformat(),
                "DownloadedAt": (now - timedelta(hours=1)).isoformat()}})
        target = args[-1]
        output = Path(args[args.index("--output") + 1])
        if "cyclonedx" in args:
            role = next(role for role, ref in self.fixture.refs.items() if ref == target)
            source = self.fixture.dir / f"images/{role}.sbom.cdx.json"
            write(output, json.loads(source.read_text(encoding="utf-8")))
        elif args[0] == "fs":
            write(output, {"ArtifactType": "filesystem", "Results": [{
                "Target": "requirements.txt", "Class": "lang-pkgs", "Type": "pip",
                "Packages": [{"Name": name, "Version": version}
                             for name, version in WORKER_PINS.items()],
                "Vulnerabilities": []}]})
        else:
            role = next(role for role, ref in self.fixture.refs.items() if ref == target)
            source = self.fixture.dir / f"images/{role}.scan.json"
            write(output, json.loads(source.read_text(encoding="utf-8")))
        return ""

    def fake_kev(self, path):
        write(path, json.loads(self.fixture.kev.read_text(encoding="utf-8")))
        return datetime.now(UTC)

    def fake_archive_inventory(self, ref, platform):
        self.inventory_calls.append((ref, platform))
        role = next(role for role, role_ref in self.fixture.refs.items() if role_ref == ref)
        _, inventory = self.fixture.archive_inventory(role)
        inventory["captured_at"] = datetime.now(UTC).isoformat()
        return inventory

    def test_release_scans_every_exact_digest_and_links_evidence(self):
        with patch.object(scan, "run_trivy", self.fake_trivy), patch.object(
            scan, "fetch_kev", self.fake_kev
        ), patch.object(
            scan, "capture_image_inventory", self.fake_archive_inventory
        ):
            result = scan.scan_release(self.fixture.manifest, self.root, self.root / "generated")
        self.assertEqual(result["images_checked"], 4)
        for ref in self.fixture.refs.values():
            self.assertEqual(sum(call[-1] == ref for call in self.calls), 2)
            self.assertTrue(all(call[call.index("--platform") + 1] == "linux/arm64"
                                for call in self.calls if call[-1] == ref))
        self.assertEqual(set(self.inventory_calls),
                         {(ref, "linux/arm64") for ref in self.fixture.refs.values()})
        self.assertTrue((self.root / "generated/evidence.json").is_file())
        self.assertTrue((self.root / "generated/decision.json").is_file())

    def test_release_rejects_missing_worker_lock_before_scanner_runs(self):
        self.fixture.lock.unlink()
        with patch.object(scan, "run_trivy", self.fake_trivy), self.assertRaisesRegex(GateError, "lock"):
            scan.scan_release(self.fixture.manifest, self.root, self.root / "generated")
        self.assertEqual(self.calls, [])

    def test_dependency_scan_targets_only_exact_lock_copy(self):
        with patch.object(scan, "run_trivy", self.fake_trivy), patch.object(
            scan, "fetch_kev", self.fake_kev
        ):
            result = scan.scan_dependencies(self.fixture.lock, self.root / "dependency-evidence")
        self.assertEqual(result["packages_checked"], len(WORKER_PINS))
        fs_call = next(call for call in self.calls if call[0] == "fs")
        self.assertEqual((Path(fs_call[-1]) / "requirements.txt").name, "requirements.txt")
        self.assertIn("--skip-db-update", fs_call)

    def test_changed_dev_direct_range_blocks_before_scanner_runs(self):
        lock = self.root / "requirements-dev.lock"
        lock.write_text("httpx==0.28.1\n", encoding="utf-8")
        direct = self.root / "requirements-dev.txt"
        direct.write_text("httpx>=0.29,<0.30\n", encoding="utf-8")
        with patch.object(scan, "run_trivy", self.fake_trivy), self.assertRaisesRegex(
            GateError, "development direct range"
        ):
            scan.scan_dependencies(lock, self.root / "dev-evidence")
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
