"""Probe the exact final synthetic worker image without network or credentials.

Run this file inside a read-only image with the reviewed worker lock mounted at
/tmp/requirements-worker.lock. The host build gate supplies the immutable image
digest; this script checks the interpreter's runtime inventory, not Dockerfile
text or an SBOM claim.
"""

from __future__ import annotations

import importlib.util
import json
import re
import site
import subprocess
import sys
import sysconfig
from importlib import metadata
from pathlib import Path

LOCK_PATH = Path("/tmp/requirements-worker.lock")
LOCK_ENTRY = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.-]*)==([^\s]+)")


def normalized(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def lock_inventory() -> dict[str, str]:
    packages: dict[str, str] = {}
    for line in LOCK_PATH.read_text(encoding="utf-8").splitlines():
        match = LOCK_ENTRY.match(line)
        if match is None:
            continue
        name, version = normalized(match.group(1)), match.group(2)
        if name in packages:
            raise AssertionError(f"duplicate locked package: {name}")
        packages[name] = version
    if len(packages) < 50:
        raise AssertionError("worker lock inventory is unexpectedly incomplete")
    return packages


def runtime_inventory() -> dict[str, str]:
    packages: dict[str, str] = {}
    for distribution in metadata.distributions():
        name = distribution.metadata["Name"]
        if not name:
            raise AssertionError("installed package without name metadata")
        key = normalized(name)
        if key in packages:
            raise AssertionError(f"duplicate installed package: {key}")
        packages[key] = distribution.version
    return packages


def main() -> None:
    build_tool_paths: list[str] = []
    if importlib.util.find_spec("pip") is not None:
        build_tool_paths.append("pip module remains importable")
    if importlib.util.find_spec("ensurepip") is not None:
        build_tool_paths.append("ensurepip module can restore bundled pip")
    stdlib = Path(sysconfig.get_path("stdlib"))
    runtime_roots = (stdlib, Path("/opt/spike"))
    archives = sorted(
        str(path)
        for root in runtime_roots
        for pattern in ("*.whl", "*.egg", "*.zip")
        for path in root.rglob(pattern)
    )
    archives.extend(
        str(path)
        for entry in sys.path
        if (path := Path(entry)).is_file() and path.suffix in {".whl", ".egg", ".zip"}
    )
    if archives:
        build_tool_paths.append(f"nested runtime archives remain: {archives}")
    bootstrap = subprocess.run(
        [sys.executable, "-m", "ensurepip", "--version"],
        capture_output=True,
        check=False,
        text=True,
        timeout=10,
    )
    if bootstrap.returncode == 0:
        build_tool_paths.append("offline ensurepip bootstrap remains available")
    for root in site.getsitepackages():
        if (Path(root) / "pip").exists():
            build_tool_paths.append("runtime pip package directory remains")
    if build_tool_paths:
        raise AssertionError("; ".join(build_tool_paths))

    locked, installed = lock_inventory(), runtime_inventory()
    mismatches = {
        name: (version, installed.get(name))
        for name, version in locked.items()
        if installed.get(name) != version
    }
    if mismatches:
        raise AssertionError(f"locked worker packages missing or changed: {mismatches}")
    extras = sorted(set(installed) - set(locked))
    if extras:
        raise AssertionError(f"unlocked runtime packages remain: {extras}")

    # Import the actual graph entrypoint and direct integration libraries.
    import deepagents  # noqa: F401
    import langchain  # noqa: F401
    import langchain_openai  # noqa: F401
    import langgraph  # noqa: F401
    import spike.worker  # noqa: F401

    print(
        json.dumps(
            {
                "status": "runtime_inventory_pass",
                "locked_packages": len(locked),
                "installed_packages": len(installed),
                "pip_importable": False,
                "ensurepip_importable": False,
                "runtime_archives": 0,
                "offline_bootstrap_available": False,
                "worker_graph_importable": True,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
