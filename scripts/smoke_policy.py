"""Shared policy for trusted Python Audio Separator smoke validation."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any


AUDIO_SEPARATOR_REPOSITORY = "https://github.com/HAGerox/python-audio-separator.git"
AUDIO_SEPARATOR_REVISION = "86f6756f8f400769c11707c48a7a27e749131a6c"
AUDIO_SEPARATOR_REQUIREMENT = (
    f"audio-separator[cpu] @ git+{AUDIO_SEPARATOR_REPOSITORY}@{AUDIO_SEPARATOR_REVISION}"
)
SMOKE_FIXTURE = "synthetic-rich-mix-v1"
PUBLIC_SMOKE_FIXTURE = "public-vocal-ccby-v1"
ACCEPTED_SMOKE_FIXTURES = {SMOKE_FIXTURE, PUBLIC_SMOKE_FIXTURE}
SMOKE_SCHEMA = 1
WEIGHT_SUFFIXES = {".ckpt", ".pth", ".onnx", ".th"}
CONFIG_SUFFIXES = {".yaml", ".yml"}
TRUSTED_ARTIFACT_ORIGINS = {"github.com", "huggingface.co", "raw.githubusercontent.com"}
TRUSTED_ARTIFACT_DELIVERY_SUFFIXES = (
    ".hf.co",
    ".xethub.hf.co",
    ".githubusercontent.com",
    ".amazonaws.com",
)


def selected_artifacts(model: dict[str, Any], backend: dict[str, Any]) -> list[dict[str, Any]]:
    names = backend.get("artifact_names", [])
    by_name = {
        artifact.get("name"): artifact
        for artifact in model.get("availability", {}).get("artifacts", [])
        if isinstance(artifact, dict) and isinstance(artifact.get("name"), str)
    }
    return [by_name[name] for name in names if name in by_name]


def contract_payload(model: dict[str, Any], backend: dict[str, Any]) -> dict[str, Any]:
    """Return the immutable portion of a backend that a smoke result attests."""

    artifacts = [
        {
            "name": artifact.get("name"),
            "url": artifact.get("url"),
            "sha256": artifact.get("sha256"),
        }
        for artifact in selected_artifacts(model, backend)
    ]
    artifacts.sort(key=lambda artifact: str(artifact.get("name")))
    outputs = [
        {
            "runtime_key": output.get("runtime_key"),
            "capability": output.get("capability"),
        }
        for output in backend.get("outputs", [])
        if isinstance(output, dict)
    ]
    outputs.sort(key=lambda output: (str(output.get("capability")), str(output.get("runtime_key"))))
    return {
        "model_filename": backend.get("model_filename"),
        "artifacts": artifacts,
        "outputs": outputs,
    }


def contract_sha256(model: dict[str, Any], backend: dict[str, Any]) -> str:
    encoded = json.dumps(
        contract_payload(model, backend), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def smoke_evidence_errors(model: dict[str, Any], backend: dict[str, Any]) -> list[str]:
    evidence = backend.get("smoke_validation")
    if not isinstance(evidence, dict):
        return ["smoke_validation is required"]
    errors: list[str] = []
    expected_outputs = sorted(
        output["runtime_key"]
        for output in backend.get("outputs", [])
        if isinstance(output, dict) and isinstance(output.get("runtime_key"), str)
    )
    checks = {
        "schema": SMOKE_SCHEMA,
        "kind": "exact_checkpoint_smoke",
        "runtime": "python-audio-separator",
        "runtime_revision": AUDIO_SEPARATOR_REVISION,
        "contract_sha256": contract_sha256(model, backend),
        "outputs": expected_outputs,
        "sample_rate": 44100,
        "channels": 2,
    }
    for field, expected in checks.items():
        if evidence.get(field) != expected:
            errors.append(f"smoke_validation.{field} must equal {expected!r}")
    if evidence.get("fixture") not in ACCEPTED_SMOKE_FIXTURES:
        errors.append(
            "smoke_validation.fixture must be a trusted smoke fixture: "
            + ", ".join(sorted(ACCEPTED_SMOKE_FIXTURES))
        )
    validated_at = evidence.get("validated_at")
    try:
        date.fromisoformat(validated_at)
    except (TypeError, ValueError):
        errors.append("smoke_validation.validated_at must be YYYY-MM-DD")
    return errors
