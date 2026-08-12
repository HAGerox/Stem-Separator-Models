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


ROOT = Path(__file__).resolve().parents[1]
ID = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
REVISION = re.compile(r"^[0-9a-f]{40}$")
BACKEND_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
MODEL_STATUSES = {"current", "specialist", "historical", "experimental", "deprecated"}
AVAILABILITY_STATES = {
    "public_weights",
}
BACKEND_STATES = {
    "validated",
    "listed",
    "declared",
    "custom_code",
    "not_listed",
    "unsupported",
    "unknown",
}
SEMANTIC_METHODS = {"source_score", "llm_derived", "listening_test"}


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

    if registry.get("schema") != 3:
        errors.append("registry.json: schema must be 3")
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
        primary_sources = evidence_policy.get("primary_sources")
        if not isinstance(primary_sources, list) or not primary_sources:
            errors.append("evidence_policy.primary_sources must be a non-empty list")
        if not isinstance(evidence_policy.get("rules"), list) or not evidence_policy["rules"]:
            errors.append("evidence_policy.rules must be a non-empty list")
        if isinstance(primary_sources, list):
            for source_id in primary_sources:
                if source_id not in snapshots:
                    errors.append(f"evidence_policy.primary_sources: unknown snapshot {source_id!r}")

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
        if metric.get("kind") not in {"measured", "semantic"}:
            errors.append(f"{where}: kind must be measured or semantic")
        if not isinstance(metric.get("label"), str) or not metric["label"]:
            errors.append(f"{where}: label is required")
        if not isinstance(metric.get("unit"), str) or not metric["unit"]:
            errors.append(f"{where}: unit is required")
        if metric.get("better") not in {"higher", "lower"}:
            errors.append(f"{where}: better must be higher or lower")
        if metric.get("kind") == "semantic":
            if not numeric(metric.get("min")) or not numeric(metric.get("max")):
                errors.append(f"{where}: semantic metrics require numeric min and max")
            elif metric["min"] >= metric["max"]:
                errors.append(f"{where}: min must be lower than max")

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

    policies = registry.get("recommendation_policies")
    if not isinstance(policies, dict) or not policies:
        errors.append("recommendation_policies must be a non-empty object")
        policies = {}
    for policy_id, policy in policies.items():
        where = f"recommendation_policies.{policy_id}"
        if not isinstance(policy_id, str) or not ID.fullmatch(policy_id):
            errors.append(f"{where}: invalid policy id")
        if not isinstance(policy, dict):
            errors.append(f"{where}: must be an object")
            continue
        measured_weight = policy.get("measured_weight")
        semantic_weight = policy.get("semantic_weight")
        if not numeric(measured_weight) or not numeric(semantic_weight):
            errors.append(f"{where}: measured_weight and semantic_weight must be numeric")
        elif abs(measured_weight + semantic_weight - 1) > 1e-9:
            errors.append(f"{where}: evidence-class weights must sum to 1")
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
                measured_total = 0.0
                semantic_total = 0.0
                for metric_id, weight in weights.items():
                    definition = metrics.get(metric_id)
                    if definition is None:
                        errors.append(f"{task_where}: unknown metric {metric_id!r}")
                    if not numeric(weight) or weight <= 0:
                        errors.append(f"{task_where}.{metric_id}: weight must be positive")
                    else:
                        total += weight
                        if definition and definition.get("kind") == "measured":
                            measured_total += weight
                        elif definition and definition.get("kind") == "semantic":
                            semantic_total += weight
                if abs(total - 1) > 1e-9:
                    errors.append(f"{task_where}: metric weights must sum to 1, got {total:g}")
                if numeric(measured_weight) and abs(measured_total - measured_weight) > 1e-7:
                    errors.append(
                        f"{task_where}: measured metric weights must sum to {measured_weight:g}, "
                        f"got {measured_total:g}"
                    )
                if numeric(semantic_weight) and abs(semantic_total - semantic_weight) > 1e-7:
                    errors.append(
                        f"{task_where}: semantic metric weights must sum to {semantic_weight:g}, "
                        f"got {semantic_total:g}"
                    )
            default_task_weights = policy.get("default_task_weights")
            if default_task_weights not in task_weights:
                errors.append(f"{where}: default_task_weights must name a task_weights entry")

    models = registry.get("models")
    if not isinstance(models, list) or not models:
        errors.append("models must be a non-empty list")
        models = []
    model_ids: set[str] = set()
    evidence_ids: set[str] = set()
    by_id: dict[str, dict] = {}
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
                if details.get("state") in {"listed", "validated"} and not any(
                    isinstance(details.get(field), str) and details[field]
                    for field in ("model_filename", "catalog_id")
                ):
                    errors.append(f"{backend_where}: listed backends require model_filename or catalog_id")
                for field in ("model_filename", "catalog_id"):
                    reference = details.get(field)
                    if reference is not None and (
                        not isinstance(reference, str) or not BACKEND_REFERENCE.fullmatch(reference)
                    ):
                        errors.append(f"{backend_where}.{field}: unsafe backend reference")
                if details.get("state") in {"validated", "listed", "declared", "custom_code"}:
                    locally_runnable = True
            if not locally_runnable:
                errors.append(f"{where}: at least one local backend path is required")

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

        observations = model.get("semantic_evidence")
        if not isinstance(observations, list):
            errors.append(f"{where}: semantic_evidence must be a list")
        else:
            for observation_index, observation in enumerate(observations):
                observation_where = f"{where}.semantic_evidence[{observation_index}]"
                if not isinstance(observation, dict):
                    errors.append(f"{observation_where}: must be an object")
                    continue
                evidence_id = observation.get("id")
                if not isinstance(evidence_id, str) or not ID.fullmatch(evidence_id):
                    errors.append(f"{observation_where}: invalid id")
                elif evidence_id in evidence_ids:
                    errors.append(f"{observation_where}: duplicate evidence id {evidence_id}")
                else:
                    evidence_ids.add(evidence_id)
                if observation.get("task") not in tasks:
                    errors.append(f"{observation_where}: task must be one of the model tasks")
                if observation.get("method") not in SEMANTIC_METHODS:
                    errors.append(f"{observation_where}: invalid method")
                confidence = observation.get("confidence")
                if not numeric(confidence) or not 0 <= confidence <= 1:
                    errors.append(f"{observation_where}: confidence must be between 0 and 1")
                values = observation.get("values")
                if not isinstance(values, dict) or not values:
                    errors.append(f"{observation_where}: values must be a non-empty object")
                else:
                    for metric_id, value in values.items():
                        definition = metrics.get(metric_id)
                        if not definition or definition.get("kind") != "semantic":
                            errors.append(f"{observation_where}: {metric_id!r} is not semantic")
                        elif not numeric(value) or not definition["min"] <= value <= definition["max"]:
                            errors.append(f"{observation_where}: {metric_id} is outside its range")
                if not isinstance(observation.get("source_id"), str) or not observation["source_id"]:
                    errors.append(f"{observation_where}: source_id is required")
                elif observation["source_id"] not in snapshots:
                    errors.append(f"{observation_where}: unknown source snapshot {observation['source_id']!r}")
                if not valid_url(observation.get("source")):
                    errors.append(f"{observation_where}: HTTPS source is required")
                location = observation.get("location")
                if not isinstance(location, dict):
                    errors.append(f"{observation_where}: location must be an object")
                else:
                    start, end = location.get("line_start"), location.get("line_end")
                    if not isinstance(start, int) or not isinstance(end, int) or start < 1 or end < start:
                        errors.append(f"{observation_where}: invalid line range")
                tags = observation.get("tags")
                if not isinstance(tags, list) or not all(isinstance(tag, str) and ID.fullmatch(tag) for tag in tags):
                    errors.append(f"{observation_where}: tags must be an id list")

        source_links = model.get("sources")
        if not isinstance(source_links, list) or not source_links or not all(valid_url(link) for link in source_links):
            errors.append(f"{where}: sources must contain HTTPS links")
        elif availability.get("repository") not in source_links:
            errors.append(f"{where}: sources must include availability.repository")

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
        if recommendation.get("policy") not in policies:
            errors.append(f"{where}: unknown policy {recommendation.get('policy')!r}")
        else:
            policy = policies[recommendation["policy"]]
            task_weights = policy.get("task_weights", {})
            if task not in task_weights and policy.get("default_task_weights") not in task_weights:
                errors.append(f"{where}: policy has no weights for this task and no valid default")
        selected_id = recommendation.get("model")
        if selected_id not in by_id:
            errors.append(f"{where}: unknown model {selected_id!r}")
        elif task not in by_id[selected_id].get("tasks", []):
            errors.append(f"{where}: model does not support {task}")
        elif by_id[selected_id]["availability"].get("state") != "public_weights":
            errors.append(f"{where}: model does not have public weights")
        elif by_id[selected_id].get("status") == "deprecated":
            errors.append(f"{where}: deprecated models cannot be defaults")
        elif by_id[selected_id].get("status") == "experimental":
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

    supported_tasks = {task for model in models for task in model.get("tasks", [])}
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
    semantic_count = sum(len(model["semantic_evidence"]) for model in models)
    task_count = len({task for model in models for task in model["tasks"]})
    print(
        f"Registry valid: {len(models)} models, {len(recommendations)} recommendations, "
        f"{task_count} model tasks, {benchmark_count} benchmarks, {semantic_count} semantic observations"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
