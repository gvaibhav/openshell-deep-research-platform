"""Fixed fixture selection and content-addressed evidence for the spike."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from spike.contract import StageManifest


class EvidenceError(ValueError):
    """A source or evidence bound was rejected."""


@dataclass(frozen=True)
class Evidence:
    source_id: str
    uri: str
    text: str
    evidence_id: str
    sha256: str

    def to_dict(self) -> dict[str, str]:
        return {"source_id": self.source_id, "uri": self.uri, "text": self.text, "evidence_id": self.evidence_id, "sha256": self.sha256}


@dataclass(frozen=True)
class FixtureCorpus:
    fixture_id: str
    fixture_sha256: str
    sources: dict[str, Evidence]

    @classmethod
    def load(cls, path: Path) -> FixtureCorpus:
        raw = path.read_bytes()
        data = json.loads(raw)
        if data.get("fixture_id") != "aurora-v1" or data.get("data_class") != "synthetic":
            raise EvidenceError("unsupported fixture")
        sources: dict[str, Evidence] = {}
        for item in data["sources"]:
            source_id = item["source_id"]
            uri = item["uri"]
            content = item["text"]
            if source_id in sources or not uri.startswith("fixture://") or not content:
                raise EvidenceError("invalid fixed source")
            digest = hashlib.sha256((source_id + "\0" + content).encode("utf-8")).hexdigest()
            sources[source_id] = Evidence(source_id, uri, content, "ev_" + digest[:24], digest)
        return cls(data["fixture_id"], hashlib.sha256(raw).hexdigest(), sources)

    def select(self, manifest: StageManifest) -> tuple[Evidence, ...]:
        if manifest.fixture_id != self.fixture_id:
            raise EvidenceError("fixture mismatch")
        try:
            selected = tuple(self.sources[source_id] for source_id in manifest.source_ids)
        except KeyError as error:
            raise EvidenceError("source not in the fixed fixture") from error
        if len(selected) > manifest.limits.max_sources:
            raise EvidenceError("source count exceeds bound")
        if sum(len(item.text.encode("utf-8")) for item in selected) > manifest.limits.max_evidence_bytes:
            raise EvidenceError("evidence bytes exceed stage bound")
        return selected


class FixtureReadTool:
    """A narrow, in-worker source tool exposed only to the retrieval agent."""

    name = "read_fixture"

    def __init__(self, selected: tuple[Evidence, ...]):
        self._selected = {item.source_id: item for item in selected}
        self.observations: list[dict[str, str | int]] = []
        self._read_ids: set[str] = set()

    def read(self, source_id: str) -> str:
        try:
            item = self._selected[source_id]
        except KeyError as error:
            self.observations.append({"source_id": source_id, "decision": "deny"})
            raise EvidenceError("source not admitted for this stage") from error
        if source_id in self._read_ids:
            self.observations.append({"source_id": source_id, "decision": "deny"})
            raise EvidenceError("source was already read in this stage")
        self._read_ids.add(source_id)
        self.observations.append({
            "source_id": source_id,
            "decision": "allow",
            "evidence_id": item.evidence_id,
            "bytes": len(item.text.encode("utf-8")),
        })
        return item.text

    def as_langchain_tool(self):
        def read_fixture(source_id: str) -> str:
            """Read one admitted synthetic fixture source by exact source ID."""
            return self.read(source_id)

        return read_fixture
