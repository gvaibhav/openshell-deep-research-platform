"""Network-disabled compatibility check for the pinned Deep Agents model body.

Run inside the disposable worker image with an explicit nonsecret route file.
The real graph and ChatOpenAI client produce requests, but MockTransport keeps
all model traffic in this process. No host credential is read or sent.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import httpx
from spike.contract import StageManifest
from spike.evidence import FixtureCorpus
from spike.model_stub import FixtureModel
from spike.relay import RelayGate, RelayRejected, RelayRoute, _strict_json
from spike.worker import (
    FIXTURE_PATH,
    DeepAgentClient,
    ResearchWorker,
    WorkerError,
    _reject_secret_environment,
)


class ConformanceFailure(RuntimeError):
    """A real pinned worker request differed from the reviewed route."""


def run(manifest_path: Path, route_path: Path) -> dict[str, Any]:
    """Exercise the actual graph and relay schema without an external socket."""
    _reject_secret_environment()
    manifest = StageManifest.load(manifest_path)
    route_fields = _strict_json(route_path.read_bytes())
    if not isinstance(route_fields, dict):
        raise ConformanceFailure("route is not an object")
    route = RelayRoute(**route_fields)
    if manifest.data_class != "synthetic" or route.data_class != "synthetic":
        raise ConformanceFailure("network-disabled fixture conformance is synthetic only")
    if manifest.stage_id != route.stage_id or manifest.data_class != route.data_class or manifest.limits.max_model_calls != route.max_requests:
        raise ConformanceFailure("manifest and route bounds differ")
    fixture = FixtureModel(route.stage_id, route.model_id, max_requests=route.max_requests)
    gate = RelayGate(route)
    shapes: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        if request.method != "POST" or request.url != httpx.URL("http://relay.spike.internal:8765/v1/chat/completions"):
            raise ConformanceFailure("worker attempted a different mock model destination")
        if request.headers.get("X-Research-Stage-Id") != route.stage_id or request.headers.get("X-Research-Data-Class") != route.data_class:
            raise ConformanceFailure("worker model headers differ from the reviewed stage route")
        if request.headers.get("Authorization") != "Bearer spike-placeholder-no-upstream-credential":
            raise ConformanceFailure("worker did not use the nonsecret placeholder")
        supplied = _strict_json(request.content)
        spend_before = gate.spend_reserved_micro_usd
        canonical = gate.reserve(supplied, route.stage_id, route.data_class)
        shapes.append({
            "fields": sorted(canonical),
            "roles": [message["role"] for message in canonical["messages"]],
            "tool_names": [tool["function"]["name"] for tool in canonical.get("tools", [])],
            "body_bytes": len(request.content),
            "reservation_micro_usd": gate.spend_reserved_micro_usd - spend_before,
        })
        return httpx.Response(200, json=fixture.answer(canonical, route.stage_id))

    client = DeepAgentClient(
        "http://relay.spike.internal:8765/v1",
        route.model_id,
        route.stage_id,
        manifest.limits.max_output_tokens,
        max_model_requests=manifest.limits.max_model_calls,
        data_class=manifest.data_class,
        http_transport=httpx.MockTransport(respond),
    )
    try:
        result = ResearchWorker(client, FixtureCorpus.load(FIXTURE_PATH)).run(manifest, manifest.stage_id, claimed_mode="mocktransport")
    finally:
        client.close()
    if not result["verified"] or [step["step"] for step in result["steps"]] != ["plan", "retrieve", "synthesize", "verify"]:
        raise ConformanceFailure("real graph did not complete four checked stages")
    if {entry["source_id"] for entry in result["retrieval_tool_calls"]} != set(manifest.source_ids):
        raise ConformanceFailure("real graph did not read exact fixture sources")
    if not 5 <= gate.requests_reserved == fixture.requests == result["model_requests_observed"] <= route.max_requests:
        raise ConformanceFailure("worker, relay, and fixture request counts differ")
    return {
        "result": "pass",
        "transport": "httpx.MockTransport; no external socket",
        "model_id": route.model_id,
        "data_class": route.data_class,
        "model_requests": gate.requests_reserved,
        "spend_reserved_micro_usd": gate.spend_reserved_micro_usd,
        "route_spend_cap_micro_usd": route.max_spend_micro_usd,
        "fixture_reads": len(result["retrieval_tool_calls"]),
        "stage_steps": [step["step"] for step in result["steps"]],
        "request_shapes": shapes,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check real pinned Deep Agents requests against the host relay schema without network")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--route", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(run(args.manifest, args.route), sort_keys=True))
        return 0
    except (ConformanceFailure, RelayRejected, WorkerError, ValueError, OSError, TypeError) as error:
        # Exception strings from client libraries may contain prompt text;
        # show a static gate error only for our own bounded exception classes.
        safe_reason = str(error) if type(error) in {ConformanceFailure, RelayRejected, WorkerError} else type(error).__name__
        print(json.dumps({"result": "fail", "reason": safe_reason}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
