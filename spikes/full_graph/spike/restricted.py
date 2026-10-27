"""Kubernetes restricted-worker comparator using the same image and fixture.

The manifest generator does not assert CNI enforcement. Its namespace and
NetworkPolicy must pass the live ingress/egress probes before matched use.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from spike.contract import StageManifest

_DNS_LABEL = re.compile(r"^[a-z][a-z0-9-]{1,61}[a-z0-9]$")
_DIGEST_IMAGE = re.compile(r"^[A-Za-z0-9./:_-]+@sha256:[0-9a-f]{64}$")
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{1,127}$")


def render_restricted_manifests(
    manifest: StageManifest,
    *,
    image_ref: str,
    worker_namespace: str,
    relay_namespace: str,
    relay_pod_ip: str,
    relay_pod_id: str,
    relay_port: int,
    model_id: str,
) -> dict[str, Any]:
    """Return ConfigMap, default-deny/relay-only policy, and one-shot Job."""
    if not _DIGEST_IMAGE.fullmatch(image_ref):
        raise ValueError("worker image must be immutable")
    if not _DNS_LABEL.fullmatch(worker_namespace) or not _DNS_LABEL.fullmatch(relay_namespace):
        raise ValueError("invalid Kubernetes namespace")
    if not _DNS_LABEL.fullmatch(relay_pod_id):
        raise ValueError("relay pod instance label must be an exact DNS label")
    try:
        ip = ipaddress.IPv4Address(relay_pod_ip)
    except ipaddress.AddressValueError as error:
        raise ValueError("relay target must be one exact IPv4 pod address") from error
    if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
        raise ValueError("invalid relay pod address")
    if type(relay_port) is not int or not 1 <= relay_port <= 65535:
        raise ValueError("invalid relay port")
    if not _MODEL_ID.fullmatch(model_id):
        raise ValueError("invalid exact model ID")
    suffix = hashlib.sha256(f"{manifest.stage_id}:{manifest.attempt_id}".encode()).hexdigest()[:10]
    name = f"research-spike-{suffix}"
    labels = {"app": "research-spike-restricted", "spike-attempt": suffix}
    relay_url = f"http://{relay_pod_ip}:{relay_port}/v1"
    stage_json = json.dumps(asdict(manifest), indent=2, sort_keys=True)
    config_map = {
        "apiVersion": "v1", "kind": "ConfigMap",
        "metadata": {"name": f"{name}-input", "namespace": worker_namespace},
        "data": {"stage.json": stage_json},
    }
    policy = {
        "apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy",
        "metadata": {"name": f"{name}-egress", "namespace": worker_namespace},
        "spec": {
            "podSelector": {"matchLabels": labels},
            "policyTypes": ["Ingress", "Egress"],
            "ingress": [],
            "egress": [{
                "to": [{
                    "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": relay_namespace}},
                    "podSelector": {"matchLabels": {"app": "research-spike-model-relay", "research-spike.org/relay-instance": relay_pod_id}},
                }],
                "ports": [{"protocol": "TCP", "port": relay_port}],
            }],
        },
    }
    job = {
        "apiVersion": "batch/v1", "kind": "Job",
        "metadata": {"name": name, "namespace": worker_namespace, "labels": labels},
        "spec": {
            "backoffLimit": 0, "activeDeadlineSeconds": 600, "ttlSecondsAfterFinished": 3600,
            "template": {
                "metadata": {"labels": labels},
                "spec": {
                    "restartPolicy": "Never",
                    "automountServiceAccountToken": False,
                    "hostNetwork": False,
                    "securityContext": {"runAsNonRoot": True, "runAsUser": 1000, "runAsGroup": 1000, "seccompProfile": {"type": "RuntimeDefault"}},
                    "containers": [{
                        "name": "research-worker",
                        "image": image_ref,
                        "imagePullPolicy": "IfNotPresent",
                        "command": [
                            "/usr/local/bin/python3.13", "-m", "spike.worker",
                            "--manifest", "/input/stage.json",
                            "--expected-stage-id", manifest.stage_id,
                            "--relay-url", relay_url,
                            "--model-id", model_id,
                            "--result", "-",
                            "--claimed-mode", "restricted",
                        ],
                        "env": [{"name": "PYTHONDONTWRITEBYTECODE", "value": "1"}, {"name": "PYTHONPATH", "value": "/opt/spike"}],
                        "securityContext": {"allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True, "capabilities": {"drop": ["ALL"]}},
                        "resources": {"requests": {"cpu": "250m", "memory": "512Mi"}, "limits": {"cpu": "2", "memory": "2Gi"}},
                        "volumeMounts": [{"name": "stage-input", "mountPath": "/input", "readOnly": True}, {"name": "tmp", "mountPath": "/tmp"}],
                    }],
                    "volumes": [{"name": "stage-input", "configMap": {"name": f"{name}-input"}}, {"name": "tmp", "emptyDir": {"sizeLimit": "128Mi"}}],
                },
            },
        },
    }
    return {"apiVersion": "v1", "kind": "List", "items": [config_map, policy, job]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render the conventional restricted-worker comparator manifests")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--worker-namespace", required=True)
    parser.add_argument("--relay-namespace", required=True)
    parser.add_argument("--relay-pod-ip", required=True)
    parser.add_argument("--relay-pod-id", required=True, help="unique research-spike.org/relay-instance label on exactly one relay Pod")
    parser.add_argument("--relay-port", type=int, required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    output = render_restricted_manifests(
        StageManifest.load(args.manifest),
        image_ref=args.image,
        worker_namespace=args.worker_namespace,
        relay_namespace=args.relay_namespace,
        relay_pod_ip=args.relay_pod_ip,
        relay_pod_id=args.relay_pod_id,
        relay_port=args.relay_port,
        model_id=args.model_id,
    )
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"rendered": str(args.output), "job": output["items"][2]["metadata"]["name"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
