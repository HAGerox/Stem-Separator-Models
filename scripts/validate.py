#!/usr/bin/env python3
"""Validate the app-facing registry without external dependencies."""

from __future__ import annotations

import json
import math
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from evidence_policy import (
    ORDINAL_CONFIDENCE_ORDER,
    ORDINAL_RECOMMENDATION_POLICIES,
    ORDINAL_RELATIONS,
    SOURCE_TIER_ORDER,
)
from product_policy import EXCLUDED_CAPABILITIES, multitrack_policy_errors


ROOT = Path(__file__).resolve().parents[1]
ID = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
REVISION = re.compile(r"^[0-9a-f]{40}$")
BACKEND_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
OUTPUT_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]*$")
MODEL_STATUSES = {"current", "specialist", "historical", "experimental", "deprecated"}
AVAILABILITY_STATES = {
    "public_weights",
}
BACKEND_STATES = {
    "validated",
    "listed",
    "compatible_unvalidated",
    "declared",
    "custom_code",
    "not_listed",
    "unsupported",
    "unknown",
}
AUDIO_SEPARATOR_ADMISSION_STATES = {
    "validated",
    "listed",
    "compatible_unvalidated",
}
LOCATION_KINDS = {"line_range", "page", "section", "json_pointer", "entry"}
LEGACY_MULTITRACK_TASKS = {"multitrack_4", "multitrack_6", "multitrack_many"}


def load(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def valid_url(value: object) -> bool:
    if not isinstance(value, str) or any(character.isspace() for character in value):
        return False
    parsed = urlparse(value)
    return (
        parsed.scheme == "https"
        and bool(parsed.netloc)
        and parsed.username is None
        and parsed.password is None
    )


def valid_date(value: object) -> bool:
    try:
        date.fromisoformat(value)  # type: ignore[arg-type]
        return True
    except (TypeError, ValueError):
        return False


def numeric(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def main() -> int:
    errors: list[str] = []
    registry_path = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "registry.json"
    registry = load(registry_path)
    watched_sources = load(ROOT / "sources.json")

    schema = registry.get("schema")
    if schema != 4:
        errors.append("registry.json: schema must be 4")
    if not valid_date(registry.get("generated_at")):
        errors.append("registry.json: generated_at must be YYYY-MM-DD")
    if not isinstance(registry.get("baseline"), bool):
        errors.append("registry.json: baseline must be boolean")
    if watched_sources.get("schema") != 1:
        errors.append("sources.json: schema must be 1")

    scope = registry.get("scope")
    if not isinstance(scope, dict):
        errors.append("scope must be an object")
    else:
        if scope.get("execution") != "local_only":
            errors.append("scope.execution must be local_only")
        if scope.get("weights") != "publicly_downloadable":
            errors.append("scope.weights must be publicly_downloadable")
        if scope.get("provider_only_models") is not False:
            errors.append("scope.provider_only_models must be false")
        if scope.get("license_metadata_required") is not True:
            errors.append("scope.license_metadata_required must be true")

    snapshots = registry.get("source_snapshots")
    if not isinstance(snapshots, dict) or not snapshots:
        errors.append("source_snapshots must be a non-empty object")
        snapshots = {}
    for snapshot_id, snapshot in snapshots.items():
        where = f"source_snapshots.{snapshot_id}"
        if not isinstance(snapshot_id, str) or not ID.fullmatch(snapshot_id):
            errors.append(f"{where}: invalid snapshot id")
        if not isinstance(snapshot, dict):
            errors.append(f"{where}: must be an object")
            continue
        if not valid_url(snapshot.get("source")):
            errors.append(f"{where}: HTTPS source is required")
        if not valid_date(snapshot.get("fetched_at")):
            errors.append(f"{where}: fetched_at must be YYYY-MM-DD")
        if "sha256" in snapshot and (
            not isinstance(snapshot["sha256"], str) or not SHA256.fullmatch(snapshot["sha256"])
        ):
            errors.append(f"{where}: sha256 must be 64 lowercase hex characters")
        tiers = snapshot.get("tiers")
        if tiers is not None:
            if not isinstance(tiers, dict) or not tiers:
                errors.append(f"{where}.tiers: must be a non-empty object")
            else:
                for claim_kind, tier in tiers.items():
                    if claim_kind not in {"qualitative", "measured", "artifact"}:
                        errors.append(f"{where}.tiers: invalid claim kind {claim_kind!r}")
                    if tier not in SOURCE_TIER_ORDER:
                        errors.append(f"{where}.tiers.{claim_kind}: invalid source tier")

    if valid_date(registry.get("generated_at")):
        generated_at = date.fromisoformat(registry["generated_at"])
        for snapshot_id, snapshot in snapshots.items():
            if isinstance(snapshot, dict) and valid_date(snapshot.get("fetched_at")):
                if date.fromisoformat(snapshot["fetched_at"]) > generated_at:
                    errors.append(f"source_snapshots.{snapshot_id}: fetched_at is after generated_at")

    evidence_policy = registry.get("evidence_policy")
    if not isinstance(evidence_policy, dict):
        errors.append("evidence_policy must be an object")
    else:
        for procedural_field in ("rules", "semantic_scale", "primary_sources"):
            if procedural_field in evidence_policy:
                errors.append(
                    f"evidence_policy.{procedural_field}: procedural policy must live in code"
                )

    metrics = registry.get("metric_definitions")
    if not isinstance(metrics, dict) or not metrics:
        errors.append("metric_definitions must be a non-empty object")
        metrics = {}
    for metric_id, metric in metrics.items():
        where = f"metric_definitions.{metric_id}"
        if not isinstance(metric_id, str) or not ID.fullmatch(metric_id):
            errors.append(f"{where}: invalid metric id")
        if not isinstance(metric, dict):
            errors.append(f"{where}: must be an object")
            continue
        if metric.get("kind") not in {"measured", "ordinal"}:
            errors.append(f"{where}: kind must be measured or ordinal")
        if not isinstance(metric.get("label"), str) or not metric["label"]:
            errors.append(f"{where}: label is required")
        if metric.get("kind") == "measured":
            if not isinstance(metric.get("unit"), str) or not metric["unit"]:
                errors.append(f"{where}: unit is required")
            if metric.get("better") not in {"higher", "lower"}:
                errors.append(f"{where}: better must be higher or lower")
        elif metric.get("kind") == "ordinal":
            for scalar_field in ("unit", "better", "min", "max"):
                if scalar_field in metric:
                    errors.append(f"{where}: ordinal metric cannot declare {scalar_field}")

    suites = registry.get("benchmark_suites")
    if not isinstance(suites, dict) or not suites:
        errors.append("benchmark_suites must be a non-empty object")
        suites = {}
    for suite_id, suite in suites.items():
        where = f"benchmark_suites.{suite_id}"
        if not isinstance(suite_id, str) or not ID.fullmatch(suite_id):
            errors.append(f"{where}: invalid suite id")
        if not isinstance(suite, dict):
            errors.append(f"{where}: must be an object")
            continue
        if not isinstance(suite.get("name"), str) or not suite["name"]:
            errors.append(f"{where}: name is required")
        if not isinstance(suite.get("version"), int) or suite["version"] < 1:
            errors.append(f"{where}: positive integer version is required")
        if not isinstance(suite.get("standardized"), bool):
            errors.append(f"{where}: standardized must be boolean")
        if not valid_url(suite.get("source")):
            errors.append(f"{where}: HTTPS source is required")
        if "dataset" in suite and not valid_url(suite["dataset"]):
            errors.append(f"{where}: dataset must be HTTPS")

    if "recommendation_policies" in registry:
        errors.append("recommendation_policies: procedural policy must live in code")
    policies = ORDINAL_RECOMMENDATION_POLICIES
    for policy_id, policy in policies.items():
        where = f"recommendation_policies.{policy_id}"
        if not isinstance(policy_id, str) or not ID.fullmatch(policy_id):
            errors.append(f"{where}: invalid policy id")
        if not isinstance(policy, dict):
            errors.append(f"{where}: must be an object")
            continue
        if policy.get("minimum_confidence") not in ORDINAL_CONFIDENCE_ORDER:
            errors.append(f"{where}: minimum_confidence is invalid")
        minimum_coverage = policy.get("minimum_coverage")
        if not numeric(minimum_coverage) or not 0 <= minimum_coverage <= 1:
            errors.append(f"{where}: minimum_coverage must be between 0 and 1")
        if policy.get("missing") != "reduce_coverage":
            errors.append(f"{where}: missing must be reduce_coverage")
        task_weights = policy.get("task_weights")
        if not isinstance(task_weights, dict) or not task_weights:
            errors.append(f"{where}: task_weights must be a non-empty object")
        else:
            for task, weights in task_weights.items():
                task_where = f"{where}.task_weights.{task}"
                if not isinstance(weights, dict) or not weights:
                    errors.append(f"{task_where}: must be a non-empty object")
                    continue
                total = 0.0
                for metric_id, weight in weights.items():
                    definition = metrics.get(metric_id)
                    if definition is None:
                        errors.append(f"{task_where}: unknown metric {metric_id!r}")
                    if not numeric(weight) or weight <= 0:
                        errors.append(f"{task_where}.{metric_id}: weight must be positive")
                    else:
                        total += weight
                if abs(total - 1) > 1e-9:
                    errors.append(f"{task_where}: metric weights must sum to 1, got {total:g}")
            default_task_weights = policy.get("default_task_weights")
            if default_task_weights not in task_weights:
                errors.append(f"{where}: default_task_weights must name a task_weights entry")

    models = registry.get("models")
    if not isinstance(models, list) or not models:
        errors.append("models must be a non-empty list")
        models = []
    model_ids: set[str] = set()
    by_id: dict[str, dict] = {}
    output_capabilities_by_model: dict[str, set[str]] = {}
    for index, model in enumerate(models):
        where = f"models[{index}]"
        if not isinstance(model, dict):
            errors.append(f"{where}: must be an object")
            continue
        model_id = model.get("id")
        if not isinstance(model_id, str) or not ID.fullmatch(model_id):
            errors.append(f"{where}: invalid id")
            continue
        if model_id in model_ids:
            errors.append(f"{where}: duplicate id {model_id}")
        model_ids.add(model_id)
        by_id[model_id] = model
        for field in ("name", "author", "architecture"):
            if not isinstance(model.get(field), str) or not model[field]:
                errors.append(f"{where}: {field} is required")
        if model.get("status") not in MODEL_STATUSES:
            errors.append(f"{where}: invalid status")
        if "released_at" in model and not valid_date(model["released_at"]):
            errors.append(f"{where}: released_at must be YYYY-MM-DD")
        tasks = model.get("tasks")
        if not isinstance(tasks, list) or not tasks or not all(isinstance(x, str) and ID.fullmatch(x) for x in tasks):
            errors.append(f"{where}: tasks must be a non-empty id list")
            tasks = []
        elif len(tasks) != len(set(tasks)):
            errors.append(f"{where}: tasks must be unique")
        legacy_multitrack = set(tasks) & LEGACY_MULTITRACK_TASKS
        if legacy_multitrack:
            errors.append(
                f"{where}: output-count multitrack tasks must be explicit decompositions: "
                + ", ".join(sorted(legacy_multitrack))
            )

        availability = model.get("availability")
        if not isinstance(availability, dict):
            errors.append(f"{where}: availability must be an object")
            availability = {}
        if availability.get("state") not in AVAILABILITY_STATES:
            errors.append(f"{where}.availability: invalid state")
        if availability.get("state") != "public_weights":
            errors.append(f"{where}.availability: registry models must have public_weights")
        license_id = availability.get("license")
        if not isinstance(license_id, str) or not license_id:
            errors.append(f"{where}.availability.license: non-empty licence metadata is required")
        if "repository" in availability and not valid_url(availability["repository"]):
            errors.append(f"{where}.availability.repository: must be HTTPS")
        if not valid_url(availability.get("repository")):
            errors.append(f"{where}.availability.repository: public repository is required")
        if "revision" in availability and (
            not isinstance(availability["revision"], str)
            or not REVISION.fullmatch(availability["revision"])
        ):
            errors.append(f"{where}.availability.revision: must be a 40-character lowercase commit")
        artifacts = availability.get("artifacts", [])
        if not isinstance(artifacts, list):
            errors.append(f"{where}.availability.artifacts: must be a list")
        else:
            artifact_names: set[str] = set()
            for artifact_index, artifact in enumerate(artifacts):
                artifact_where = f"{where}.availability.artifacts[{artifact_index}]"
                if not isinstance(artifact, dict):
                    errors.append(f"{artifact_where}: must be an object")
                    continue
                name = artifact.get("name")
                if not isinstance(name, str) or not name:
                    errors.append(f"{artifact_where}: name is required")
                elif name in artifact_names:
                    errors.append(f"{artifact_where}: duplicate name {name}")
                else:
                    artifact_names.add(name)
                if not valid_url(artifact.get("url")):
                    errors.append(f"{artifact_where}: HTTPS url is required")
                if not isinstance(artifact.get("sha256"), str) or not SHA256.fullmatch(artifact["sha256"]):
                    errors.append(f"{artifact_where}: sha256 must be 64 lowercase hex characters")
        backends = model.get("backends")
        model_output_capabilities: set[str] = set()
        if not isinstance(backends, dict):
            errors.append(f"{where}: backends must be an object")
        else:
            locally_runnable = False
            for backend, details in backends.items():
                backend_where = f"{where}.backends.{backend}"
                if not isinstance(details, dict):
                    errors.append(f"{backend_where}: must be an object")
                    continue
                if details.get("state") not in BACKEND_STATES:
                    errors.append(f"{backend_where}: invalid state")
                if not isinstance(details.get("validated"), bool):
                    errors.append(f"{backend_where}: validated must be boolean")
                if details.get("validated") and details.get("state") != "validated":
                    errors.append(f"{backend_where}: validated=true requires state=validated")
                if details.get("state") in AUDIO_SEPARATOR_ADMISSION_STATES and not any(
                    isinstance(details.get(field), str) and details[field]
                    for field in ("model_filename", "catalog_id")
                ):
                    errors.append(
                        f"{backend_where}: admitted backends require model_filename or catalog_id"
                    )
                for field in ("model_filename", "catalog_id"):
                    reference = details.get(field)
                    if reference is not None and (
                        not isinstance(reference, str) or not BACKEND_REFERENCE.fullmatch(reference)
                    ):
                        errors.append(f"{backend_where}.{field}: unsafe backend reference")
                catalog_snapshot = details.get("catalog_snapshot")
                if catalog_snapshot is not None:
                    if catalog_snapshot not in snapshots:
                        errors.append(f"{backend_where}.catalog_snapshot: unknown source snapshot")
                    elif not snapshots[catalog_snapshot].get("sha256"):
                        errors.append(
                            f"{backend_where}.catalog_snapshot: snapshot must have a SHA-256"
                        )
                outputs = details.get("outputs")
                if details.get("state") in AUDIO_SEPARATOR_ADMISSION_STATES and not outputs:
                    errors.append(f"{backend_where}: admitted backends require exact outputs")
                if outputs is not None:
                    if not isinstance(outputs, list) or not outputs:
                        errors.append(f"{backend_where}.outputs: must be a non-empty list")
                    else:
                        runtime_keys: set[str] = set()
                        capabilities: set[str] = set()
                        for output_index, output in enumerate(outputs):
                            output_where = f"{backend_where}.outputs[{output_index}]"
                            if isinstance(output, dict):
                                runtime_key = output.get("runtime_key")
                                capability = output.get("capability")
                                if "label" in output and (
                                    not isinstance(output["label"], str) or not output["label"]
                                ):
                                    errors.append(f"{output_where}.label: must be non-empty")
                            else:
                                errors.append(
                                    f"{output_where}: must be an explicit output object"
                                )
                                continue
                            if not isinstance(runtime_key, str) or not OUTPUT_KEY.fullmatch(runtime_key):
                                errors.append(f"{output_where}.runtime_key: invalid exact output key")
                            else:
                                runtime_keys.add(runtime_key)
                            if not isinstance(capability, str) or not ID.fullmatch(capability):
                                errors.append(f"{output_where}.capability: invalid capability id")
                            elif capability in capabilities:
                                errors.append(f"{output_where}.capability: duplicate {capability!r}")
                            else:
                                capabilities.add(capability)
                                model_output_capabilities.add(capability)
                artifact_names = details.get("artifact_names")
                if artifact_names is not None:
                    if (
                        not isinstance(artifact_names, list)
                        or not artifact_names
                        or not all(isinstance(name, str) and name for name in artifact_names)
                        or len(artifact_names) != len(set(artifact_names))
                    ):
                        errors.append(f"{backend_where}.artifact_names: must be a unique string list")
                    else:
                        known_artifacts = {
                            artifact.get("name")
                            for artifact in artifacts
                            if isinstance(artifact, dict)
                        }
                        missing_artifacts = set(artifact_names) - known_artifacts
                        if missing_artifacts:
                            errors.append(
                                f"{backend_where}.artifact_names: unknown artifacts "
                                + ", ".join(sorted(missing_artifacts))
                            )
                if details.get("state") in {
                    "validated",
                    "listed",
                    "compatible_unvalidated",
                    "declared",
                    "custom_code",
                }:
                    locally_runnable = True
            audio_separator = backends.get("audio_separator")
            if not isinstance(audio_separator, dict):
                errors.append(
                    f"{where}.backends.audio_separator: admitted registry models must declare this backend"
                )
            elif audio_separator.get("state") not in AUDIO_SEPARATOR_ADMISSION_STATES:
                errors.append(
                    f"{where}.backends.audio_separator: state must be validated, listed, or compatible_unvalidated"
                )
            elif audio_separator.get("state") == "compatible_unvalidated":
                if audio_separator.get("validated") is not False:
                    errors.append(
                        f"{where}.backends.audio_separator: compatible_unvalidated requires validated=false"
                    )
                if not isinstance(audio_separator.get("model_filename"), str):
                    errors.append(
                        f"{where}.backends.audio_separator: compatible_unvalidated requires model_filename"
                    )
                selected_artifact_names = audio_separator.get("artifact_names", [])
                selected_artifacts = [
                    artifact
                    for artifact in artifacts
                    if isinstance(artifact, dict)
                    and artifact.get("name") in selected_artifact_names
                ]
                if not any(
                    Path(artifact["name"]).suffix.lower()
                    in {".ckpt", ".pth", ".onnx", ".th"}
                    for artifact in selected_artifacts
                ) or not any(
                    Path(artifact["name"]).suffix.lower() in {".yaml", ".yml"}
                    for artifact in selected_artifacts
                ):
                    errors.append(
                        f"{where}.backends.audio_separator: compatible_unvalidated requires selected checkpoint and YAML artifacts"
                    )
            if not locally_runnable:
                errors.append(f"{where}: at least one local backend path is required")
        output_capabilities_by_model[model_id] = model_output_capabilities

        decompositions = model.get("decompositions", {})
        if not isinstance(decompositions, dict):
            errors.append(f"{where}.decompositions: must be an object")
        else:
            for decomposition_id, decomposition in decompositions.items():
                decomposition_where = f"{where}.decompositions.{decomposition_id}"
                if not isinstance(decomposition_id, str) or not ID.fullmatch(decomposition_id):
                    errors.append(f"{decomposition_where}: invalid decomposition id")
                if not isinstance(decomposition, dict):
                    errors.append(f"{decomposition_where}: must be an object")
                    continue
                decomposition_outputs = decomposition.get("outputs")
                if not isinstance(decomposition_outputs, list) or not decomposition_outputs or not all(
                    isinstance(item, str) and ID.fullmatch(item) for item in decomposition_outputs
                ):
                    errors.append(f"{decomposition_where}.outputs: must be a non-empty id list")
                elif len(decomposition_outputs) != len(set(decomposition_outputs)):
                    errors.append(f"{decomposition_where}.outputs: must be unique")
                elif not set(decomposition_outputs).issubset(model_output_capabilities):
                    missing_outputs = set(decomposition_outputs) - model_output_capabilities
                    errors.append(
                        f"{decomposition_where}.outputs: missing backend contracts for "
                        + ", ".join(sorted(missing_outputs))
                    )
        benchmarks = model.get("benchmarks")
        if not isinstance(benchmarks, list):
            errors.append(f"{where}: benchmarks must be a list")
        else:
            benchmark_keys: set[tuple[object, object]] = set()
            for result_index, result in enumerate(benchmarks):
                result_where = f"{where}.benchmarks[{result_index}]"
                if not isinstance(result, dict):
                    errors.append(f"{result_where}: must be an object")
                    continue
                suite_id = result.get("suite")
                stem = result.get("stem")
                benchmark_key = (suite_id, stem)
                if benchmark_key in benchmark_keys:
                    errors.append(f"{result_where}: duplicate suite/stem result")
                benchmark_keys.add(benchmark_key)
                if suite_id not in suites:
                    errors.append(f"{result_where}: unknown suite {suite_id!r}")
                if not isinstance(stem, str) or not ID.fullmatch(stem):
                    errors.append(f"{result_where}: stem must be an id")
                values = result.get("values")
                if not isinstance(values, dict) or not values:
                    errors.append(f"{result_where}: values must be a non-empty object")
                else:
                    for metric_id, value in values.items():
                        definition = metrics.get(metric_id)
                        if not definition or definition.get("kind") != "measured":
                            errors.append(f"{result_where}: {metric_id!r} is not a measured metric")
                        if not numeric(value):
                            errors.append(f"{result_where}: {metric_id} must be a finite number")
                if not valid_url(result.get("source")):
                    errors.append(f"{result_where}: HTTPS source is required")
                if not isinstance(result.get("config"), dict):
                    errors.append(f"{result_where}: config must be an object")

        if "semantic_evidence" in model:
            errors.append(f"{where}: semantic_evidence is not allowed in schema 4")

        source_links = model.get("sources")
        if not isinstance(source_links, list) or not source_links or not all(valid_url(link) for link in source_links):
            errors.append(f"{where}: sources must contain HTTPS links")
        elif availability.get("repository") not in source_links:
            errors.append(f"{where}: sources must include availability.repository")

    contexts = registry.get("evidence_contexts")
    if not isinstance(contexts, dict):
        errors.append("evidence_contexts must be an object")
        contexts = {}
    if isinstance(contexts, dict):
        for context_id, context_definition in contexts.items():
            where = f"evidence_contexts.{context_id}"
            if not isinstance(context_id, str) or not ID.fullmatch(context_id):
                errors.append(f"{where}: invalid context id")
            if not isinstance(context_definition, dict):
                errors.append(f"{where}: must be an object")
                continue
            for field in ("scope", "protocol"):
                if not isinstance(context_definition.get(field), str) or not context_definition[field]:
                    errors.append(f"{where}.{field}: non-empty string is required")
            stem_mapping = context_definition.get("stem_mapping")
            if not isinstance(stem_mapping, dict) or not stem_mapping:
                errors.append(f"{where}.stem_mapping: non-empty object is required")
            elif not all(
                isinstance(key, str)
                and ID.fullmatch(key)
                and isinstance(value, str)
                and ID.fullmatch(value)
                for key, value in stem_mapping.items()
            ):
                errors.append(f"{where}.stem_mapping: keys and values must be ids")
            conditions = context_definition.get("conditions")
            if not isinstance(conditions, list) or not all(
                isinstance(condition, str) and ID.fullmatch(condition)
                for condition in conditions
            ):
                errors.append(f"{where}.conditions: must be an id list")

        ordinal_rows = registry.get("ordinal_evidence")
        if not isinstance(ordinal_rows, list):
            errors.append("ordinal_evidence must be a list")
            ordinal_rows = []
        ordinal_count = len(ordinal_rows)
        ordinal_ids: set[str] = set()
        source_fingerprints: set[str] = set()
        for index, observation in enumerate(ordinal_rows):
            where = f"ordinal_evidence[{index}]"
            if not isinstance(observation, dict):
                errors.append(f"{where}: must be an object")
                continue
            evidence_id = observation.get("id")
            if not isinstance(evidence_id, str) or not ID.fullmatch(evidence_id):
                errors.append(f"{where}: invalid id")
            elif evidence_id in ordinal_ids:
                errors.append(f"{where}: duplicate evidence id {evidence_id}")
            else:
                ordinal_ids.add(evidence_id)
            task = observation.get("task")
            if not isinstance(task, str) or not ID.fullmatch(task):
                errors.append(f"{where}.task: must be an id")
            metric_id = observation.get("metric")
            if metric_id not in metrics or metrics.get(metric_id, {}).get("kind") != "ordinal":
                errors.append(f"{where}.metric: must name an ordinal metric")
            if observation.get("context") not in contexts:
                errors.append(f"{where}.context: unknown evidence context")
            if observation.get("relation") not in ORDINAL_RELATIONS:
                errors.append(f"{where}.relation: invalid ordinal relation")
            if observation.get("confidence") not in ORDINAL_CONFIDENCE_ORDER:
                errors.append(f"{where}.confidence: invalid confidence")

            endpoint_models: list[str] = []
            for side in ("left", "right"):
                endpoint = observation.get(side)
                endpoint_where = f"{where}.{side}"
                if not isinstance(endpoint, dict):
                    errors.append(f"{endpoint_where}: must be an object")
                    continue
                model_id = endpoint.get("model")
                if not isinstance(model_id, str) or model_id not in by_id:
                    errors.append(f"{endpoint_where}.model: unknown model {model_id!r}")
                else:
                    endpoint_models.append(model_id)
                    if task not in by_id[model_id].get("tasks", []):
                        errors.append(f"{endpoint_where}.model: model does not support {task!r}")
                if "config" in endpoint and not isinstance(endpoint["config"], dict):
                    errors.append(f"{endpoint_where}.config: must be an object")
            if len(endpoint_models) == 2:
                if endpoint_models[0] == endpoint_models[1]:
                    errors.append(f"{where}: comparison endpoints must differ")
                elif endpoint_models[0] > endpoint_models[1]:
                    errors.append(f"{where}: endpoints must be in canonical model-id order")

            source = observation.get("source")
            if not isinstance(source, dict):
                errors.append(f"{where}.source: must be an object")
            else:
                snapshot_id = source.get("snapshot")
                if snapshot_id not in snapshots:
                    errors.append(f"{where}.source.snapshot: unknown source snapshot")
                else:
                    snapshot = snapshots[snapshot_id]
                    source_tiers = snapshot.get("tiers", {}) if isinstance(snapshot, dict) else {}
                    if source_tiers.get("qualitative") not in SOURCE_TIER_ORDER:
                        errors.append(
                            f"{where}.source.snapshot: source has no qualitative evidence tier"
                        )
                if not valid_url(source.get("entry_url")):
                    errors.append(f"{where}.source.entry_url: HTTPS URL is required")
                location = source.get("location")
                if not isinstance(location, dict) or location.get("kind") not in LOCATION_KINDS:
                    errors.append(f"{where}.source.location: invalid typed location")
                elif location["kind"] == "line_range":
                    start, end = location.get("start"), location.get("end")
                    if not isinstance(start, int) or not isinstance(end, int) or start < 1 or end < start:
                        errors.append(f"{where}.source.location: invalid line range")
                elif location["kind"] == "page":
                    if not isinstance(location.get("page"), int) or location["page"] < 1:
                        errors.append(f"{where}.source.location.page: positive integer is required")
                else:
                    if not isinstance(location.get("value"), str) or not location["value"]:
                        errors.append(f"{where}.source.location.value: non-empty string is required")
                if evidence_id and isinstance(evidence_id, str):
                    fingerprint = json.dumps(
                        {
                            "task": task,
                            "metric": metric_id,
                            "context": observation.get("context"),
                            "left": observation.get("left"),
                            "right": observation.get("right"),
                            "relation": observation.get("relation"),
                            "source": source,
                        },
                        sort_keys=True,
                    )
                    if fingerprint in source_fingerprints:
                        errors.append(f"{where}: duplicate normalized source observation")
                    source_fingerprints.add(fingerprint)

            tags = observation.get("tags", [])
            if not isinstance(tags, list) or not all(
                isinstance(tag, str) and ID.fullmatch(tag) for tag in tags
            ):
                errors.append(f"{where}.tags: must be an id list")
            if "paraphrase" in observation and (
                not isinstance(observation["paraphrase"], str) or not observation["paraphrase"]
            ):
                errors.append(f"{where}.paraphrase: must be a non-empty string")
            if not isinstance(observation.get("summary"), str) or not observation["summary"]:
                errors.append(f"{where}.summary: non-empty source summary is required")
    recommendations = registry.get("recommendations")
    if not isinstance(recommendations, dict) or not recommendations:
        errors.append("recommendations must be a non-empty object")
        recommendations = {}
    for task, recommendation in recommendations.items():
        where = f"recommendations.{task}"
        if not isinstance(task, str) or not ID.fullmatch(task):
            errors.append(f"{where}: invalid task id")
        if not isinstance(recommendation, dict):
            errors.append(f"{where}: must be an object")
            continue
        if task in LEGACY_MULTITRACK_TASKS:
            errors.append(f"{where}: replace output-count recommendation with multitrack")
        if recommendation.get("policy") not in policies:
            errors.append(f"{where}: unknown policy {recommendation.get('policy')!r}")
        else:
            policy = policies[recommendation["policy"]]
            task_weights = policy.get("task_weights", {})
            if (
                task != "multitrack"
                and task not in task_weights
                and policy.get("default_task_weights") not in task_weights
            ):
                errors.append(f"{where}: policy has no weights for this task and no valid default")
        selected_id = recommendation.get("model")
        if selected_id not in by_id:
            errors.append(f"{where}: unknown model {selected_id!r}")
        else:
            selected = by_id[selected_id]
            if task == "multitrack":
                decomposition_id = recommendation.get("decomposition")
                decomposition = selected.get("decompositions", {}).get(decomposition_id)
                if not isinstance(decomposition_id, str) or not ID.fullmatch(decomposition_id):
                    errors.append(f"{where}: decomposition id is required")
                elif decomposition is None:
                    errors.append(f"{where}: model does not declare decomposition {decomposition_id!r}")
                else:
                    for violation in multitrack_policy_errors(decomposition):
                        errors.append(f"{where}: {violation}")
            elif task not in selected.get("tasks", []):
                errors.append(f"{where}: model does not support {task}")
            if selected["availability"].get("state") != "public_weights":
                errors.append(f"{where}: model does not have public weights")
            if selected.get("status") == "deprecated":
                errors.append(f"{where}: deprecated models cannot be defaults")
            elif selected.get("status") == "experimental":
                stable_candidates = [
                    model["id"]
                    for model in models
                    if task in model.get("tasks", [])
                    and model.get("status") not in {"experimental", "deprecated"}
                    and model.get("availability", {}).get("state") == "public_weights"
                ]
                if stable_candidates:
                    errors.append(
                        f"{where}: experimental default is not allowed while stable candidates exist: "
                        + ", ".join(stable_candidates)
                    )
        alternatives = recommendation.get("alternatives")
        if not isinstance(alternatives, list):
            errors.append(f"{where}: alternatives must be a list")
        else:
            seen: set[str] = set()
            for index, alternative in enumerate(alternatives):
                alt_where = f"{where}.alternatives[{index}]"
                if not isinstance(alternative, dict):
                    errors.append(f"{alt_where}: must be an object")
                    continue
                model_id = alternative.get("model")
                if model_id not in by_id:
                    errors.append(f"{alt_where}: unknown model {model_id!r}")
                elif task == "multitrack":
                    alternative_decomposition = alternative.get("decomposition")
                    decomposition = by_id[model_id].get("decompositions", {}).get(
                        alternative_decomposition
                    )
                    if decomposition is None:
                        errors.append(f"{alt_where}: valid decomposition is required")
                    else:
                        for violation in multitrack_policy_errors(decomposition):
                            errors.append(f"{alt_where}: {violation}")
                elif task not in by_id[model_id].get("tasks", []):
                    errors.append(f"{alt_where}: model does not support {task}")
                if model_id in seen or model_id == recommendation.get("model"):
                    errors.append(f"{alt_where}: duplicate recommendation target {model_id!r}")
                seen.add(model_id)
                if not isinstance(alternative.get("specialty"), str) or not ID.fullmatch(alternative["specialty"]):
                    errors.append(f"{alt_where}: specialty must be an id")
        delivery = recommendation.get("delivery")
        if delivery is not None:
            delivery_where = f"{where}.delivery"
            if not isinstance(delivery, dict):
                errors.append(f"{delivery_where}: must be an object")
            else:
                if delivery.get("sum_to_mix") is not True:
                    errors.append(f"{delivery_where}: sum_to_mix must be true")
                if delivery.get("mode") != "residual_to_stem":
                    errors.append(f"{delivery_where}: mode must be residual_to_stem")
                residual_stem = delivery.get("residual_stem")
                if not isinstance(residual_stem, str) or residual_stem not in by_id.get(selected_id, {}).get("tasks", []):
                    errors.append(f"{delivery_where}: residual_stem must be produced by the model")

        if (
            selected_id in output_capabilities_by_model
            and task not in EXCLUDED_CAPABILITIES
            and task != "multitrack"
            and task not in output_capabilities_by_model[selected_id]
        ):
            errors.append(f"{where}: selected model has no exact backend output for {task}")

    supported_tasks = {task for model in models for task in model.get("tasks", [])}
    if any(model.get("decompositions") for model in models):
        supported_tasks.add("multitrack")
    recommendation_tasks = set(recommendations)
    for task in sorted(supported_tasks - recommendation_tasks):
        errors.append(f"recommendations: missing task {task!r}")
    for task in sorted(recommendation_tasks - supported_tasks):
        errors.append(f"recommendations: task {task!r} is not supported by any model")

    for task in ("vocals", "instrumental"):
        recommendation = recommendations.get(task)
        if not isinstance(recommendation, dict):
            continue
        selected = by_id.get(recommendation.get("model"), {})
        evaluator_supported = any(
            isinstance(details, dict)
            and details.get("state") in {"listed", "validated"}
            and any(
                isinstance(details.get(field), str) and details[field]
                for field in ("model_filename", "catalog_id")
            )
            for backend, details in selected.get("backends", {}).items()
            if backend in {"audio_separator", "pymss"}
        )
        if not evaluator_supported:
            errors.append(f"recommendations.{task}: default must support the listening evaluator")

    watched = watched_sources.get("sources")
    if not isinstance(watched, list) or not watched:
        errors.append("sources.json: sources must be a non-empty list")
    else:
        names: set[str] = set()
        for index, source in enumerate(watched):
            where = f"sources[{index}]"
            if not isinstance(source, dict):
                errors.append(f"{where}: must be an object")
                continue
            name = source.get("name")
            if not isinstance(name, str) or not name:
                errors.append(f"{where}: name is required")
            elif name in names:
                errors.append(f"{where}: duplicate source name {name}")
            else:
                names.add(name)
            if not valid_url(source.get("url")):
                errors.append(f"{where}: HTTPS url is required")
            if "fetch_url" in source and not valid_url(source["fetch_url"]):
                errors.append(f"{where}: fetch_url must be HTTPS")
            if not isinstance(source.get("enabled"), bool):
                errors.append(f"{where}: enabled must be boolean")
            if source.get("role") not in {"primary_qualitative", "primary_quantitative", "supplementary"}:
                errors.append(f"{where}: invalid role")
            look_for = source.get("look_for")
            if not isinstance(look_for, list) or not look_for or not all(isinstance(item, str) for item in look_for):
                errors.append(f"{where}: look_for must be a non-empty string list")

    if errors:
        print("Registry validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    benchmark_count = sum(len(model["benchmarks"]) for model in models)
    task_count = len({task for model in models for task in model["tasks"]})
    print(
        f"Registry valid: {len(models)} models, {len(recommendations)} recommendations, "
        f"{task_count} model tasks, {benchmark_count} benchmarks, "
        f"{ordinal_count} ordinal comparisons"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
