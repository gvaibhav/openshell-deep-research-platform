"""Generate one exact OpenShell v0.1.5 relay rule for the disposable spike."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

_DNS_HOST = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])$")
_PYTHON_PATH = "/usr/local/bin/python3.13"


def make_policy(relay_host: str, relay_port: int, python_path: str = _PYTHON_PATH) -> dict[str, Any]:
    if not _DNS_HOST.fullmatch(relay_host) or relay_host.startswith(".") or ".." in relay_host or "*" in relay_host:
        raise ValueError("relay host must be one exact DNS name")
    if type(relay_port) is not int or not 1 <= relay_port <= 65535:
        raise ValueError("invalid relay port")
    if python_path != _PYTHON_PATH:
        raise ValueError("Python path must match the qualified worker image")
    return {
        "version": 1,
        # OpenShell v0.1.5 applies filesystem grants at sandbox startup. The
        # baked package needs its parent /opt traversable as well as /opt/spike
        # readable; a later policy update cannot repair a running sandbox.
        "filesystem_policy": {
            "include_workdir": True,
            "read_only": ["/opt", "/opt/spike", "/usr", "/lib", "/etc", "/var/log", "/proc", "/dev/urandom"],
            "read_write": ["/tmp", "/dev/null"],
        },
        "landlock": {"compatibility": "hard_requirement"},
        "network_policies": {
            "model_relay": {
                "endpoints": [{
                    "host": relay_host,
                    "port": relay_port,
                    "protocol": "rest",
                    "enforcement": "enforce",
                    "rules": [{"allow": {"method": "POST", "path": "/v1/chat/completions"}}],
                }],
                "binaries": [{"path": python_path}],
            }
        },
    }


def write_policy(path: Path, relay_host: str, relay_port: int) -> str:
    """Write JSON, a YAML subset, and return its SHA-256 digest."""
    raw = (json.dumps(make_policy(relay_host, relay_port), sort_keys=True, indent=2) + "\n").encode("utf-8")
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def policy_allows(policy: dict[str, Any], host: str, port: int, method: str, path: str, binary: str) -> bool:
    """Static check of this template only; never a substitute for a live denial."""
    rule = policy["network_policies"]["model_relay"]
    endpoint = rule["endpoints"][0]
    return (
        endpoint["host"] == host
        and endpoint["port"] == port
        and endpoint["enforcement"] == "enforce"
        and endpoint["protocol"] == "rest"
        and endpoint["rules"] == [{"allow": {"method": method, "path": path}}]
        and rule["binaries"] == [{"path": binary}]
    )
