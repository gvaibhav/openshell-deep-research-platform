"""Inventory archive candidates in a Docker image's effective final root filesystem.

The image is never started. Docker resolves the requested immutable ref and
platform, creates a stopped container, and exports its flattened filesystem.
This inspects bytes visible to that container, including files from inherited
layers that remain visible, rather than treating whiteouted layer bytes as live.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import secrets
import select
import subprocess
import tarfile
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

from scripts.build_security.gate import IMAGE_PLATFORM, IMAGE_REF, GateError

MAX_EXPORT_BYTES = 8 * 1024**3
MAX_ENTRIES = 1_000_000
MAX_CANDIDATES = 10_000
MAX_PATH_LENGTH = 4096
EXPORT_TIMEOUT_SECONDS = 15 * 60
DOCKER_TIMEOUT_SECONDS = 60
READ_CHUNK = 1024 * 1024
SHA256 = re.compile(r"^sha256:[a-f0-9]{64}$")
CONTAINER_NONCE_LABEL = "org.openshell-deep-research.archive-inventory-nonce"
ARCHIVE_SUFFIXES = (
    ".whl",
    ".egg",
    ".zip",
    ".jar",
    ".pyz",
    ".gem",
    ".deb",
    ".rpm",
    ".apk",
    ".tar",
    ".tar.gz",
    ".tar.bz2",
    ".tar.xz",
    ".tar.zst",
    ".tgz",
)
VENDOR_COMPONENTS = {
    "vendor",
    "_vendor",
    "vendored",
    "third_party",
    "_third_party",
    "third-party",
    "thirdparty",
}
VENDOR_MANIFESTS = {
    "vendor.txt",
    "modules.txt",
    "metadata",
    "pkg-info",
    "package.json",
    "package-lock.json",
    "pyproject.toml",
    "poetry.lock",
    "requirements.txt",
    "go.mod",
    "go.sum",
    "cargo.toml",
    "cargo.lock",
    "record",
    "setup.py",
    "setup.cfg",
    "pipfile",
    "pipfile.lock",
    "uv.lock",
    "gemfile",
    "gemfile.lock",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "composer.json",
    "composer.lock",
    "yarn.lock",
    "pnpm-lock.yaml",
    "bom.cdx.json",
    "sbom.cdx.json",
    "bom.spdx.json",
    "sbom.spdx.json",
    "bom.json",
    "sbom.json",
    "spdx.json",
    "cyclonedx.json",
    "bom.spdx",
    "sbom.spdx",
}
VENDOR_MANIFEST_SUFFIXES = (".gemspec", ".nuspec", ".csproj")
ZIP_MAGIC = {b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"}


def _tar_path(name: str) -> str:
    """Canonicalize an export member without extracting it anywhere."""
    if (
        not isinstance(name, str)
        or not name
        or len(name) > MAX_PATH_LENGTH
        or (name.startswith("/") or "\\" in name or "\x00" in name)
    ):
        raise GateError("archive inventory has unsafe member path")
    while name.startswith("./"):
        name = name[2:]
    if name in ("", "."):
        return "/"
    parts = name.rstrip("/").split("/")
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise GateError("archive inventory has unsafe member path")
    return "/" + "/".join(parts)


def _candidate_reason(path: str, prefix: bytes = b"") -> str | None:
    lower = path.lower()
    if lower.endswith(ARCHIVE_SUFFIXES):
        return "archive_name"
    if prefix in ZIP_MAGIC:
        return "zip_magic"
    parts = lower.strip("/").split("/")
    basename = parts[-1]
    if any(part in VENDOR_COMPONENTS for part in parts[:-1]):
        if (
            basename in VENDOR_MANIFESTS
            or basename.endswith(VENDOR_MANIFEST_SUFFIXES)
            or (
                basename.startswith("requirements")
                and basename.endswith((".txt", ".in"))
            )
        ):
            return "vendored_manifest"
        return "vendored_file"
    return None


class _HashedReader(io.RawIOBase):
    """Bound a streamed Docker export and hash every byte through real EOF."""

    def __init__(self, source: IO[bytes], *, deadline: float | None = None):
        self.source = source
        self.deadline = deadline
        self.sha256 = hashlib.sha256()
        self.bytes_read = 0
        self.tail = b""

    def readable(self) -> bool:
        return True

    def read(self, requested: int = READ_CHUNK) -> bytes:
        size = READ_CHUNK if requested < 0 else min(requested, READ_CHUNK)
        if size == 0:
            return b""
        if self.deadline is not None:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise GateError("archive inventory Docker export timed out")
            try:
                ready, _, _ = select.select([self.source], [], [], remaining)
            except OSError as exc:
                raise GateError(
                    "archive inventory Docker export stream failed"
                ) from exc
            if not ready:
                raise GateError("archive inventory Docker export timed out")
            try:
                chunk = os.read(self.source.fileno(), size)
            except OSError as exc:
                raise GateError(
                    "archive inventory Docker export stream failed"
                ) from exc
        else:
            chunk = self.source.read(size)
        if not isinstance(chunk, bytes):
            raise GateError("archive inventory Docker export returned invalid bytes")
        self.bytes_read += len(chunk)
        if self.bytes_read > MAX_EXPORT_BYTES:
            raise GateError("archive inventory Docker export exceeds byte limit")
        self.sha256.update(chunk)
        self.tail = (self.tail + chunk)[-1024:]
        return chunk


def inventory_tar_stream(
    source: IO[bytes], *, deadline: float | None = None
) -> dict[str, Any]:
    """Return bounded, content-hashed candidates from one flattened export tar.

    This function never extracts files. A candidate remains a release blocker;
    this first version has no archive exception/disposition mechanism.
    """
    reader = _HashedReader(source, deadline=deadline)
    candidates: list[dict[str, Any]] = []
    paths: set[str] = set()
    entries_seen = 0
    regular_files_seen = 0
    try:
        with tarfile.open(fileobj=reader, mode="r|") as archive:
            for member in archive:
                entries_seen += 1
                if entries_seen > MAX_ENTRIES:
                    raise GateError("archive inventory exceeds entry limit")
                path = _tar_path(member.name)
                if path in paths and path != "/":
                    raise GateError(
                        f"archive inventory has duplicate member path: {path}"
                    )
                paths.add(path)
                if member.size < 0 or member.size > MAX_EXPORT_BYTES:
                    raise GateError("archive inventory has invalid member size")
                if member.isfile():
                    regular_files_seen += 1
                    fileobj = archive.extractfile(member)
                    if fileobj is None:
                        raise GateError("archive inventory cannot read regular member")
                    prefix = fileobj.read(4)
                    reason = _candidate_reason(path, prefix)
                    if reason is not None:
                        hasher = hashlib.sha256(prefix)
                        size = len(prefix)
                        while chunk := fileobj.read(READ_CHUNK):
                            size += len(chunk)
                            hasher.update(chunk)
                        if size != member.size:
                            raise GateError(
                                "archive inventory truncated candidate member"
                            )
                        candidates.append(
                            {
                                "path": path,
                                "kind": "regular",
                                "reason": reason,
                                "size": size,
                                "sha256": hasher.hexdigest(),
                            }
                        )
                elif member.isdir():
                    continue
                else:
                    reason = _candidate_reason(path)
                    if reason is not None:
                        if not (member.issym() or member.islnk()):
                            raise GateError(
                                "archive inventory has unsupported archive member type"
                            )
                        candidates.append(
                            {
                                "path": path,
                                "kind": "symlink" if member.issym() else "hardlink",
                                "reason": reason,
                                "size": 0,
                                "sha256": None,
                                "link_target": member.linkname,
                            }
                        )
                if len(candidates) > MAX_CANDIDATES:
                    raise GateError("archive inventory exceeds candidate limit")
            # tarfile stops at the end-of-archive marker, which need not be the
            # pipe EOF. Drain the Docker export so its checksum and exit status
            # cover all emitted bytes before declaring the inventory complete.
            while reader.read(READ_CHUNK):
                pass
    except GateError:
        raise
    except (tarfile.TarError, EOFError, OSError, ValueError) as exc:
        raise GateError("archive inventory tar is malformed or truncated") from exc
    if (
        reader.bytes_read < 10240
        or reader.bytes_read % 512
        or reader.tail != bytes(1024)
    ):
        raise GateError("archive inventory tar is incomplete")
    if entries_seen < 1 or regular_files_seen < 1:
        raise GateError("archive inventory has no regular file coverage")
    return {
        "export_sha256": reader.sha256.hexdigest(),
        "export_bytes": reader.bytes_read,
        "entries_seen": entries_seen,
        "regular_files_seen": regular_files_seen,
        "candidates": candidates,
    }


def _docker_run(args: list[str], *, timeout: int = DOCKER_TIMEOUT_SECONDS) -> str:
    try:
        result = subprocess.run(
            ["docker", *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GateError(
            f"archive inventory Docker {args[0]} unavailable or timed out"
        ) from exc
    if result.returncode:
        raise GateError(
            f"archive inventory Docker {args[0]} failed with exit {result.returncode}"
        )
    return result.stdout.strip()


def _docker_json(args: list[str]) -> dict[str, Any]:
    try:
        parsed = json.loads(_docker_run(args))
    except json.JSONDecodeError as exc:
        raise GateError(
            "archive inventory Docker inspect returned invalid JSON"
        ) from exc
    if (
        not isinstance(parsed, list)
        or len(parsed) != 1
        or not isinstance(parsed[0], dict)
    ):
        raise GateError(
            "archive inventory Docker inspect returned an unexpected image count"
        )
    return parsed[0]


def _export_container_inventory(container_id: str) -> dict[str, Any]:
    try:
        process = subprocess.Popen(
            ["docker", "container", "export", container_id],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        raise GateError("archive inventory Docker export unavailable") from exc
    try:
        if process.stdout is None:
            raise GateError("archive inventory Docker export has no byte stream")
        summary = inventory_tar_stream(
            process.stdout,
            deadline=time.monotonic() + EXPORT_TIMEOUT_SECONDS,
        )
        try:
            exit_code = process.wait(timeout=DOCKER_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as exc:
            raise GateError("archive inventory Docker export exit timed out") from exc
        if exit_code:
            raise GateError(
                f"archive inventory Docker export failed with exit {exit_code}"
            )
        return summary
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        if process.stdout is not None:
            process.stdout.close()


def _resolved_image_identity(
    image: dict[str, Any], platform: str
) -> tuple[str, str, list[str]]:
    """Keep Docker's image ID, child descriptor, and rootfs layers separate."""
    os_name, architecture = platform.split("/")
    image_id = image.get("Id")
    descriptor = image.get("Descriptor")
    child_digest = descriptor.get("digest") if isinstance(descriptor, dict) else None
    child_platform = (
        descriptor.get("platform") if isinstance(descriptor, dict) else None
    )
    rootfs = image.get("RootFS")
    diff_ids = rootfs.get("Layers") if isinstance(rootfs, dict) else None
    if (
        not isinstance(image_id, str)
        or not SHA256.fullmatch(image_id)
        or (image.get("Os"), image.get("Architecture")) != (os_name, architecture)
        or not isinstance(child_digest, str)
        or (not SHA256.fullmatch(child_digest))
        or not isinstance(child_platform, dict)
        or (child_platform.get("os"), child_platform.get("architecture"))
        != (os_name, architecture)
        or not isinstance(rootfs, dict)
        or (rootfs.get("Type") != "layers")
        or not isinstance(diff_ids, list)
        or not 1 <= len(diff_ids) <= 1000
        or not all(
            isinstance(value, str) and SHA256.fullmatch(value) for value in diff_ids
        )
    ):
        raise GateError(
            "archive inventory resolved image does not match requested platform"
        )
    return image_id, child_digest, diff_ids


def _cidfile_id(path: Path) -> str | None:
    try:
        value = path.read_text(encoding="ascii").strip()
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError) as exc:
        raise GateError(
            "archive inventory cannot read Docker container ID file"
        ) from exc
    if not re.fullmatch(r"[a-f0-9]{64}", value):
        raise GateError("archive inventory Docker container ID file is invalid")
    return value


def _inspect_owned_created(
    container_id: str,
    ref: str,
    name: str,
    nonce: str,
    expected_image_id: str | None = None,
) -> dict[str, Any]:
    """Attest our stopped create before export or any deletion."""
    container = _docker_json(["container", "inspect", container_id])
    config = container.get("Config")
    labels = config.get("Labels") if isinstance(config, dict) else None
    state = container.get("State")
    host = container.get("HostConfig")
    actual_image_id = container.get("Image")
    if (
        container.get("Id") != container_id
        or container.get("Name") != f"/{name}"
        or (not isinstance(config, dict) or config.get("Image") != ref)
        or not isinstance(labels, dict)
        or labels.get(CONTAINER_NONCE_LABEL) != nonce
        or (
            not isinstance(actual_image_id, str)
            or not SHA256.fullmatch(actual_image_id)
        )
        or (expected_image_id is not None and actual_image_id != expected_image_id)
        or (
            not isinstance(state, dict)
            or state.get("Status") != "created"
            or state.get("Running") is not False
            or state.get("Pid") != 0
        )
        or (
            not isinstance(host, dict)
            or host.get("NetworkMode") != "none"
            or host.get("ReadonlyRootfs") is not True
        )
    ):
        raise GateError(
            "archive inventory container ownership or stopped state unverified"
        )
    return container


def capture_image_inventory(ref: str, platform: str) -> dict[str, Any]:
    """Resolve and export one immutable image/platform without starting it."""
    if not IMAGE_REF.fullmatch(ref) or not IMAGE_PLATFORM.fullmatch(platform):
        raise GateError(
            "archive inventory requires an exact digest and supported platform"
        )
    try:
        image = _docker_json(["image", "inspect", "--platform", platform, ref])
    except GateError:
        # Trivy may fetch into its own cache without adding the image to Docker.
        # Pull the same immutable ref/platform, then inspect again; create itself
        # never silently pulls a different image.
        _docker_run(
            ["image", "pull", "--platform", platform, ref],
            timeout=EXPORT_TIMEOUT_SECONDS,
        )
        image = _docker_json(["image", "inspect", "--platform", platform, ref])
    os_name, architecture = platform.split("/")
    image_id, child_digest, rootfs_diff_ids = _resolved_image_identity(image, platform)
    nonce = secrets.token_hex(16)
    name = f"research-archive-inventory-{nonce}"
    with tempfile.TemporaryDirectory(prefix="archive-inventory-cid-") as directory:
        cidfile = Path(directory) / "container.id"
        matched_id: str | None = None
        container_image_id: str | None = None
        try:
            try:
                create_output = _docker_run(
                    [
                        "container",
                        "create",
                        "--cidfile",
                        str(cidfile),
                        "--name",
                        name,
                        "--label",
                        f"{CONTAINER_NONCE_LABEL}={nonce}",
                        "--pull=never",
                        "--platform",
                        platform,
                        "--network=none",
                        "--read-only",
                        ref,
                    ]
                )
            except GateError as exc:
                raise GateError(
                    f"archive inventory create uncertain for {name}; "
                    f"manual reconciliation required: {exc}"
                ) from exc
            try:
                container_id = _cidfile_id(cidfile)
            except GateError as exc:
                raise GateError(
                    f"archive inventory CID uncertain for {name}; manual reconciliation "
                    f"required: {exc}"
                ) from exc
            if container_id is None or create_output != container_id:
                raise GateError(
                    f"archive inventory Docker create returned inconsistent container IDs "
                    f"for {name}; manual reconciliation required"
                )
            matched_id = container_id
            container = _inspect_owned_created(container_id, ref, name, nonce)
            container_image_id = container.get("Image")
            assert isinstance(container_image_id, str)
            # Docker may report an index digest in Container.Image and a child
            # manifest/config identity in ImageInspect.Id. Resolve both paths
            # with the requested platform; these hashes need not be equal.
            created_image = _docker_json(
                [
                    "image",
                    "inspect",
                    "--platform",
                    platform,
                    container_image_id,
                ]
            )
            if _resolved_image_identity(created_image, platform) != (
                image_id,
                child_digest,
                rootfs_diff_ids,
            ):
                raise GateError(
                    "archive inventory resolved image changed during container create"
                )
            summary = _export_container_inventory(container_id)
        finally:
            if matched_id is not None:
                if _cidfile_id(cidfile) != matched_id:
                    raise GateError(
                        f"archive inventory CID changed for {name}; "
                        "manual container reconciliation required"
                    )
                try:
                    _inspect_owned_created(
                        matched_id, ref, name, nonce, container_image_id
                    )
                except GateError as exc:
                    raise GateError(
                        f"archive inventory cleanup ownership uncertain for {name}; "
                        "manual reconciliation required"
                    ) from exc
                # No --force: if it starts after inspection, Docker refuses rm.
                _docker_run(["container", "rm", "--volumes", matched_id])
    return {
        "schema_version": 2,
        "source": "docker-container-export",
        "ref": ref,
        "platform": platform,
        "resolved_image_id": image_id,
        "resolved_descriptor_digest": child_digest,
        "container_image_id": container_image_id,
        "rootfs_diff_ids": rootfs_diff_ids,
        "observed_os": os_name,
        "observed_architecture": architecture,
        "captured_at": datetime.now(UTC).isoformat(),
        **summary,
        "complete": True,
    }
