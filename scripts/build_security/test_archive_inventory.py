"""Effective-rootfs archive coverage uses synthetic tar files and a fake Docker CLI."""

from __future__ import annotations

import hashlib
import io
import tarfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.build_security import archive_inventory
from scripts.build_security.gate import GateError


def tar_stream(entries: list[tuple[str, str, bytes | str]]) -> io.BytesIO:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as tar:
        for name, kind, content in entries:
            member = tarfile.TarInfo(name)
            if kind == "regular":
                assert isinstance(content, bytes)
                member.size = len(content)
                tar.addfile(member, io.BytesIO(content))
            else:
                assert isinstance(content, str)
                member.type = tarfile.SYMTYPE if kind == "symlink" else tarfile.LNKTYPE
                member.linkname = content
                tar.addfile(member)
    output.seek(0)
    return output


def docker_image(observed_id: str, layer_id: str | None = None) -> dict[str, object]:
    layer_id = layer_id or "sha256:" + "e" * 64
    return {
        "Id": observed_id,
        "Os": "linux",
        "Architecture": "arm64",
        "Descriptor": {
            "digest": observed_id,
            "platform": {"os": "linux", "architecture": "arm64"},
        },
        "RootFS": {"Type": "layers", "Layers": [layer_id]},
    }


def created_container(
    container_id: str,
    ref: str,
    create_args: list[str],
    *,
    image_id: str | None = None,
    running: bool = False,
    nonce_override: str | None = None,
) -> dict[str, object]:
    name = create_args[create_args.index("--name") + 1]
    nonce = create_args[create_args.index("--label") + 1].split("=", 1)[1]
    return {
        "Id": container_id,
        "Name": f"/{name}",
        "Image": image_id or "sha256:" + "d" * 64,
        "Config": {
            "Image": ref,
            "Labels": {
                archive_inventory.CONTAINER_NONCE_LABEL: nonce_override or nonce
            },
        },
        "State": {
            "Status": "running" if running else "created",
            "Running": running,
            "Pid": 123 if running else 0,
        },
        "HostConfig": {"NetworkMode": "none", "ReadonlyRootfs": True},
    }


class ArchiveInventoryTests(unittest.TestCase):
    def test_clean_rootfs_and_ordinary_installed_dist_info_have_no_candidates(self):
        source = tar_stream(
            [
                (
                    "usr/local/lib/python3.13/site-packages/sample-1.0.dist-info/METADATA",
                    "regular",
                    b"Name: sample\n",
                ),
                (
                    "usr/local/lib/python3.13/site-packages/sample/module.py",
                    "regular",
                    b"x = 1\n",
                ),
            ]
        )
        result = archive_inventory.inventory_tar_stream(source)
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["regular_files_seen"], 2)
        self.assertEqual(
            result["export_sha256"], hashlib.sha256(source.getvalue()).hexdigest()
        )
        self.assertEqual(result["export_bytes"], len(source.getvalue()))

    def test_nested_ensurepip_wheel_is_detected_by_path_and_hashed(self):
        payload = b"PK\x03\x04bundled pip vendor code"
        source = tar_stream(
            [
                (
                    "usr/local/lib/python3.13/ensurepip/_bundled/pip-25.2-py3-none-any.whl",
                    "regular",
                    payload,
                ),
            ]
        )
        result = archive_inventory.inventory_tar_stream(source)
        self.assertEqual(
            result["candidates"],
            [
                {
                    "path": "/usr/local/lib/python3.13/ensurepip/_bundled/pip-25.2-py3-none-any.whl",
                    "kind": "regular",
                    "reason": "archive_name",
                    "size": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            ],
        )

    def test_zip_magic_catches_archive_with_unexpected_name(self):
        source = tar_stream(
            [("opt/app/cache/blob.bin", "regular", b"PK\x03\x04hidden")]
        )
        result = archive_inventory.inventory_tar_stream(source)
        self.assertEqual(result["candidates"][0]["reason"], "zip_magic")
        self.assertEqual(result["candidates"][0]["path"], "/opt/app/cache/blob.bin")

    def test_vendored_manifest_is_distinct_from_installed_dist_info(self):
        source = tar_stream(
            [
                (
                    "usr/local/lib/python3.13/site-packages/sample/_vendor/thing/package.json",
                    "regular",
                    b'{"name":"thing"}',
                ),
            ]
        )
        result = archive_inventory.inventory_tar_stream(source)
        self.assertEqual(result["candidates"][0]["reason"], "vendored_manifest")

    def test_common_vendored_build_manifests_are_candidates(self):
        source = tar_stream(
            [
                (
                    "opt/app/third_party/library/setup.py",
                    "regular",
                    b"from setuptools import setup",
                ),
                ("opt/app/third_party/library/pom.xml", "regular", b"<project />"),
            ]
        )
        result = archive_inventory.inventory_tar_stream(source)
        self.assertEqual(
            [entry["reason"] for entry in result["candidates"]],
            ["vendored_manifest", "vendored_manifest"],
        )

    def test_unpacked_vendor_bom_and_source_are_candidates(self):
        source = tar_stream(
            [
                (
                    "opt/app/_vendor/bom.cdx.json",
                    "regular",
                    b'{"bomFormat":"CycloneDX"}',
                ),
                (
                    "opt/app/_vendor/urllib3/__init__.py",
                    "regular",
                    b"__version__ = '1.0'\n",
                ),
            ]
        )
        result = archive_inventory.inventory_tar_stream(source)
        self.assertEqual(
            [entry["reason"] for entry in result["candidates"]],
            ["vendored_manifest", "vendored_file"],
        )

    def test_nested_vendor_installable_and_link_are_candidates(self):
        source = tar_stream(
            [
                ("opt/app/_vendor/pkg/lib.whl", "regular", b"PK\x03\x04nested"),
                ("opt/app/_vendor/pkg/alias.py", "symlink", "lib.whl"),
            ]
        )
        result = archive_inventory.inventory_tar_stream(source)
        self.assertEqual(
            [entry["reason"] for entry in result["candidates"]],
            ["archive_name", "vendored_file"],
        )

    def test_archive_symlink_and_hardlink_are_candidates(self):
        source = tar_stream(
            [
                ("tmp/cache/pip.bin", "regular", b"not an archive"),
                ("tmp/pip.whl", "symlink", "../cache/pip.bin"),
                ("tmp/copy.whl", "hardlink", "tmp/cache/pip.bin"),
            ]
        )
        result = archive_inventory.inventory_tar_stream(source)
        self.assertEqual(
            [entry["kind"] for entry in result["candidates"]], ["symlink", "hardlink"]
        )

    def test_traversal_absolute_and_duplicate_tar_names_fail_coverage(self):
        cases = (
            [("../pip.whl", "regular", b"zip")],
            [("/tmp/pip.whl", "regular", b"zip")],
            [("tmp/a", "regular", b"a"), ("tmp/a", "regular", b"b")],
        )
        for entries in cases:
            with (
                self.subTest(entries=entries),
                self.assertRaisesRegex(GateError, "archive inventory.*path"),
            ):
                archive_inventory.inventory_tar_stream(tar_stream(entries))

    def test_truncated_tar_and_bounded_entry_count_fail_coverage(self):
        source = tar_stream([("tmp/a", "regular", b"a"), ("tmp/b", "regular", b"b")])
        with (
            patch.object(archive_inventory, "MAX_ENTRIES", 1),
            self.assertRaisesRegex(GateError, "archive inventory.*entry"),
        ):
            archive_inventory.inventory_tar_stream(source)
        truncated = tar_stream([("tmp/pip.whl", "regular", b"content")])
        truncated.seek(0)
        with self.assertRaisesRegex(GateError, "archive inventory"):
            archive_inventory.inventory_tar_stream(
                io.BytesIO(truncated.getvalue()[:520])
            )

    def test_export_failure_still_removes_only_created_container(self):
        ref = "example.org/worker@sha256:" + "a" * 64
        container_id = "b" * 64
        observed_id = "sha256:" + "c" * 64
        calls: list[list[str]] = []
        create_args: list[str] = []

        def docker_run(args: list[str], *, timeout: int = 60) -> str:
            calls.append(args)
            if args[:2] == ["container", "create"]:
                create_args[:] = args
                Path(args[args.index("--cidfile") + 1]).write_text(
                    container_id, encoding="ascii"
                )
                return container_id
            return ""

        def docker_json(args: list[str]) -> dict[str, object]:
            if args[:2] == ["image", "inspect"]:
                return docker_image(observed_id)
            return created_container(container_id, ref, create_args)

        with (
            patch.object(archive_inventory, "_docker_run", side_effect=docker_run),
            patch.object(archive_inventory, "_docker_json", side_effect=docker_json),
            patch.object(
                archive_inventory,
                "_export_container_inventory",
                side_effect=GateError("export failed"),
            ),
            self.assertRaisesRegex(GateError, "export failed"),
        ):
            archive_inventory.capture_image_inventory(ref, "linux/arm64")
        self.assertIn(["container", "rm", "--volumes", container_id], calls)
        self.assertFalse(any("--force" in args for args in calls))

    def test_wrong_resolved_container_image_or_platform_fails_before_export_and_cleans_up(
        self,
    ):
        ref = "example.org/worker@sha256:" + "a" * 64
        container_id = "b" * 64
        calls: list[list[str]] = []
        create_args: list[str] = []

        def docker_run(args: list[str], *, timeout: int = 60) -> str:
            calls.append(args)
            if args[:2] == ["container", "create"]:
                create_args[:] = args
                Path(args[args.index("--cidfile") + 1]).write_text(
                    container_id, encoding="ascii"
                )
                return container_id
            return ""

        def docker_json(args: list[str]) -> dict[str, object]:
            if args[:2] == ["image", "inspect"]:
                return docker_image("sha256:" + ("c" if args[-1] == ref else "e") * 64)
            return created_container(container_id, ref, create_args)

        with (
            patch.object(archive_inventory, "_docker_run", side_effect=docker_run),
            patch.object(archive_inventory, "_docker_json", side_effect=docker_json),
            patch.object(archive_inventory, "_export_container_inventory") as export,
            self.assertRaisesRegex(GateError, "resolved image"),
        ):
            archive_inventory.capture_image_inventory(ref, "linux/arm64")
        export.assert_not_called()
        self.assertIn(["container", "rm", "--volumes", container_id], calls)

    def test_create_error_after_cidfile_leaves_uncertain_container_for_reconciliation(
        self,
    ):
        ref = "example.org/worker@sha256:" + "a" * 64
        container_id = "b" * 64
        observed_id = "sha256:" + "c" * 64
        calls: list[list[str]] = []

        def docker_run(args: list[str], *, timeout: int = 60) -> str:
            calls.append(args)
            if args[:2] == ["container", "create"]:
                Path(args[args.index("--cidfile") + 1]).write_text(
                    container_id, encoding="ascii"
                )
                raise GateError("create failed after ID write")
            return ""

        with (
            patch.object(archive_inventory, "_docker_run", side_effect=docker_run),
            patch.object(
                archive_inventory,
                "_docker_json",
                return_value=docker_image(observed_id),
            ),
            self.assertRaisesRegex(GateError, "create failed"),
        ):
            archive_inventory.capture_image_inventory(ref, "linux/arm64")
        self.assertFalse(any(args[:2] == ["container", "rm"] for args in calls))

    def test_malformed_cidfile_denies_and_leaves_uncertain_container(self):
        ref = "example.org/worker@sha256:" + "a" * 64
        container_id = "b" * 64
        observed_id = "sha256:" + "c" * 64
        calls: list[list[str]] = []

        def docker_run(args: list[str], *, timeout: int = 60) -> str:
            calls.append(args)
            if args[:2] == ["container", "create"]:
                Path(args[args.index("--cidfile") + 1]).write_text(
                    "broken", encoding="ascii"
                )
                return container_id
            return ""

        with (
            patch.object(archive_inventory, "_docker_run", side_effect=docker_run),
            patch.object(
                archive_inventory,
                "_docker_json",
                return_value=docker_image(observed_id),
            ),
            self.assertRaisesRegex(GateError, "container ID file is invalid"),
        ):
            archive_inventory.capture_image_inventory(ref, "linux/arm64")
        self.assertFalse(any(args[:2] == ["container", "rm"] for args in calls))

    def test_stdout_cid_disagreement_does_not_remove_unattested_id(self):
        ref = "example.org/worker@sha256:" + "a" * 64
        stdout_id, cidfile_id = "b" * 64, "c" * 64
        observed_id = "sha256:" + "d" * 64
        calls: list[list[str]] = []

        def docker_run(args: list[str], *, timeout: int = 60) -> str:
            calls.append(args)
            if args[:2] == ["container", "create"]:
                Path(args[args.index("--cidfile") + 1]).write_text(
                    cidfile_id, encoding="ascii"
                )
                return stdout_id
            return ""

        with (
            patch.object(archive_inventory, "_docker_run", side_effect=docker_run),
            patch.object(
                archive_inventory,
                "_docker_json",
                return_value=docker_image(observed_id),
            ),
            self.assertRaisesRegex(GateError, "inconsistent container IDs"),
        ):
            archive_inventory.capture_image_inventory(ref, "linux/arm64")
        self.assertFalse(any(args[:2] == ["container", "rm"] for args in calls))

    def test_running_container_is_not_removed_after_export_failure(self):
        ref = "example.org/worker@sha256:" + "a" * 64
        container_id = "b" * 64
        observed_id = "sha256:" + "c" * 64
        calls: list[list[str]] = []
        create_args: list[str] = []

        def docker_run(args: list[str], *, timeout: int = 60) -> str:
            calls.append(args)
            if args[:2] == ["container", "create"]:
                create_args[:] = args
                Path(args[args.index("--cidfile") + 1]).write_text(
                    container_id, encoding="ascii"
                )
                return container_id
            return ""

        def docker_json(args: list[str]) -> dict[str, object]:
            if args[:2] == ["image", "inspect"]:
                return docker_image(observed_id)
            return created_container(container_id, ref, create_args, running=True)

        with (
            patch.object(archive_inventory, "_docker_run", side_effect=docker_run),
            patch.object(archive_inventory, "_docker_json", side_effect=docker_json),
            patch.object(
                archive_inventory,
                "_export_container_inventory",
                side_effect=GateError("export failed"),
            ),
            self.assertRaises(GateError),
        ):
            archive_inventory.capture_image_inventory(ref, "linux/arm64")
        self.assertFalse(any(args[:2] == ["container", "rm"] for args in calls))

    def test_container_started_after_export_is_not_removed(self):
        ref = "example.org/worker@sha256:" + "a" * 64
        container_id = "b" * 64
        observed_id = "sha256:" + "c" * 64
        calls: list[list[str]] = []
        create_args: list[str] = []
        container_inspects = 0

        def docker_run(args: list[str], *, timeout: int = 60) -> str:
            calls.append(args)
            if args[:2] == ["container", "create"]:
                create_args[:] = args
                Path(args[args.index("--cidfile") + 1]).write_text(
                    container_id, encoding="ascii"
                )
                return container_id
            return ""

        def docker_json(args: list[str]) -> dict[str, object]:
            nonlocal container_inspects
            if args[:2] == ["image", "inspect"]:
                return docker_image(observed_id)
            container_inspects += 1
            return created_container(
                container_id, ref, create_args, running=container_inspects > 1
            )

        with (
            patch.object(archive_inventory, "_docker_run", side_effect=docker_run),
            patch.object(archive_inventory, "_docker_json", side_effect=docker_json),
            patch.object(
                archive_inventory,
                "_export_container_inventory",
                return_value={
                    "export_sha256": "a" * 64,
                    "export_bytes": 10240,
                    "entries_seen": 1,
                    "regular_files_seen": 1,
                    "candidates": [],
                },
            ),
            self.assertRaisesRegex(GateError, "cleanup ownership uncertain"),
        ):
            archive_inventory.capture_image_inventory(ref, "linux/arm64")
        self.assertEqual(container_inspects, 2)
        self.assertFalse(any(args[:2] == ["container", "rm"] for args in calls))

    def test_wrong_nonce_or_image_never_removes_container(self):
        ref = "example.org/worker@sha256:" + "a" * 64
        container_id = "b" * 64
        observed_id = "sha256:" + "c" * 64

        def check_case(wrong: str) -> None:
            calls: list[list[str]] = []
            create_args: list[str] = []

            def docker_run(args: list[str], *, timeout: int = 60) -> str:
                calls.append(args)
                if args[:2] == ["container", "create"]:
                    create_args[:] = args
                    Path(args[args.index("--cidfile") + 1]).write_text(
                        container_id, encoding="ascii"
                    )
                    return container_id
                return ""

            def docker_json(args: list[str]) -> dict[str, object]:
                if args[:2] == ["image", "inspect"]:
                    return docker_image(observed_id)
                container = created_container(
                    container_id,
                    ref,
                    create_args,
                    nonce_override="not-our-nonce" if wrong == "nonce" else None,
                )
                if wrong == "image":
                    container["Config"]["Image"] = (
                        "example.org/other@sha256:" + "f" * 64
                    )
                return container

            with (
                patch.object(archive_inventory, "_docker_run", side_effect=docker_run),
                patch.object(
                    archive_inventory, "_docker_json", side_effect=docker_json
                ),
                patch.object(
                    archive_inventory, "_export_container_inventory"
                ) as export,
                self.assertRaises(GateError),
            ):
                archive_inventory.capture_image_inventory(ref, "linux/arm64")
            export.assert_not_called()
            self.assertFalse(any(args[:2] == ["container", "rm"] for args in calls))

        for wrong in ("nonce", "image"):
            with self.subTest(wrong=wrong):
                check_case(wrong)


if __name__ == "__main__":
    unittest.main()
