"""Strict, intentionally small stage manifest for the disposable spike."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class StageManifestError(ValueError):
    """The stage input is not an admitted synthetic/public spike request."""


_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{1,79}$")
_FIXTURE_ID = "aurora-v1"
_MAX_QUESTION_CHARS = 800


def _strict_keys(data: dict[str, Any], required: set[str], optional: set[str] | frozenset[str] = frozenset()) -> None:
    missing = required - data.keys()
    extra = data.keys() - required - optional
    if missing or extra:
        raise StageManifestError(f"invalid manifest fields (missing={sorted(missing)}, extra={sorted(extra)})")


def _integer(data: dict[str, Any], key: str, minimum: int, maximum: int) -> int:
    value = data[key]
    if type(value) is not int or not minimum <= value <= maximum:
        raise StageManifestError(f"{key} must be an integer in [{minimum}, {maximum}]")
    return value


@dataclass(frozen=True)
class Limits:
    max_sources: int
    max_evidence_bytes: int
    max_model_calls: int
    max_response_chars: int
    max_output_tokens: int = 256

    @classmethod
    def from_dict(cls, value: Any) -> Limits:
        if not isinstance(value, dict):
            raise StageManifestError("limits must be an object")
        _strict_keys(value, {"max_sources", "max_evidence_bytes", "max_model_calls", "max_response_chars"}, {"max_output_tokens"})
        output = value.get("max_output_tokens", 256)
        if type(output) is not int or not 1 <= output <= 1024:
            raise StageManifestError("max_output_tokens must be in [1, 1024]")
        result = cls(
            max_sources=_integer(value, "max_sources", 1, 4),
            max_evidence_bytes=_integer(value, "max_evidence_bytes", 64, 4096),
            max_model_calls=_integer(value, "max_model_calls", 4, 8),
            max_response_chars=_integer(value, "max_response_chars", 128, 4096),
            max_output_tokens=output,
        )
        return result


@dataclass(frozen=True)
class StageManifest:
    schema_version: str
    job_id: str
    stage_id: str
    attempt_id: str
    fixture_id: str
    data_class: str
    question: str
    source_ids: tuple[str, ...]
    limits: Limits

    @classmethod
    def from_dict(cls, value: Any) -> StageManifest:
        if not isinstance(value, dict):
            raise StageManifestError("stage manifest must be an object")
        _strict_keys(value, {"schema_version", "job_id", "stage_id", "attempt_id", "fixture_id", "data_class", "question", "source_ids", "limits"})
        if value["schema_version"] != "spike.stage.v1":
            raise StageManifestError("unsupported stage manifest version")
        for key in ("job_id", "stage_id", "attempt_id"):
            if not isinstance(value[key], str) or not _ID.fullmatch(value[key]):
                raise StageManifestError(f"invalid {key}")
        if value["fixture_id"] != _FIXTURE_ID:
            raise StageManifestError("only the embedded aurora-v1 fixture is admitted")
        if value["data_class"] not in ("synthetic", "public"):
            raise StageManifestError("private data is outside this spike")
        question = value["question"]
        if not isinstance(question, str) or not question.strip() or len(question) > _MAX_QUESTION_CHARS:
            raise StageManifestError("question is empty or too long")
        sources = value["source_ids"]
        if not isinstance(sources, list) or not sources or not all(isinstance(s, str) and _ID.fullmatch(s) for s in sources):
            raise StageManifestError("source_ids must be a nonempty list of IDs")
        if len(set(sources)) != len(sources):
            raise StageManifestError("duplicate source_id")
        limits = Limits.from_dict(value["limits"])
        if len(sources) > limits.max_sources:
            raise StageManifestError("source count exceeds stage limit")
        return cls(
            schema_version=value["schema_version"],
            job_id=value["job_id"],
            stage_id=value["stage_id"],
            attempt_id=value["attempt_id"],
            fixture_id=value["fixture_id"],
            data_class=value["data_class"],
            question=question.strip(),
            source_ids=tuple(sources),
            limits=limits,
        )

    @classmethod
    def load(cls, path: Path) -> StageManifest:
        if path.stat().st_size > 16_384:
            raise StageManifestError("stage manifest exceeds 16 KiB")
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def bind(self, expected_stage_id: str) -> None:
        if self.stage_id != expected_stage_id:
            raise StageManifestError("stage ID does not match the launcher binding")
