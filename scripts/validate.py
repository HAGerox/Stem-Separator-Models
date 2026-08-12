#!/usr/bin/env python3
"""Validate the app-facing registry without external dependencies."""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
ID = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
MODEL_STATUSES = {"recommended", "experimental", "deprecated"}
QUALITY_METHODS = {"source_score", "llm_derived", "listening_test"}


def load(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def valid_url(value: object) -> bool:
    return isinstance(value, str) and urlparse(value).scheme == "https"


def valid_date(value: object) -> bool:
    try:
        date.fromisoformat(value)  # type: ignore[arg-type]
        return True
    except (TypeError, ValueError):
        return False


def main() -> int:
    errors: list[str] = []
    registry_path = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "registry.json"
    registry = load(registry_path)
    watched_sources = load(ROOT / "sources.json")

    if registry.get("schema") != 2:
        errors.append("registry.json: schema must be 2")
    if watched_sources.get("schema") != 1:
        errors.append("sources.json: schema must be 1")

    metrics = registry.get("metric_definitions")
    if not isinstance(metrics, dict) or not metrics:
        errors.append("metric_definitions must be a non-empty object")
        metrics = {}
    for metric_id, metric in metrics.items():
        where = f"metric_definitions.{metric_id}"
        if not ID.fullmatch(metric_id) or not isinstance(metric, dict):
            errors.append(f"{where}: invalid metric definition")
            continue
        if metric.get("kind") not in {"measured", "normalized"}:
            errors.append(f"{where}: kind must be measured or normalized")
        if not isinstance(metric.get("label"), str) or not metric["label"]:
            errors.append(f"{where}: label is required")
        if not isinstance(metric.get("unit"), str) or not metric["unit"]:
            errors.append(f"{where}: unit is required")
        if metric.get("better") not in {"higher", "lower"}:
            errors.append(f"{where}: better must be higher or lower")
        if metric.get("kind") == "normalized":
            if not isinstance(metric.get("min"), (int, float)):
                errors.append(f"{where}: normalized metric requires min")
            if not isinstance(metric.get("max"), (int, float)):
                errors.append(f"{where}: normalized metric requires max")

    suites = registry.get("benchmark_suites")
    if not isinstance(suites, dict) or not suites:
        errors.append("benchmark_suites must be a non-empty object")
        suites = {}
    for suite_id, suite in suites.items():
        where = f"benchmark_suites.{suite_id}"
        if not ID.fullmatch(suite_id) or not isinstance(suite, dict):
            errors.append(f"{where}: invalid suite definition")
            continue
        if not isinstance(suite.get("name"), str) or not suite["name"]:
            errors.append(f"{where}: name is required")
        if not isinstance(suite.get("version"), int) or suite["version"] < 1:
            errors.append(f"{where}: positive integer version is required")
        if not isinstance(suite.get("standardized"), bool):
            errors.append(f"{where}: standardized must be boolean")
        if not valid_url(suite.get("protocol")):
            errors.append(f"{where}: HTTPS protocol is required")
        if not valid_url(suite.get("source")):
            errors.append(f"{where}: HTTPS source is required")
        suite_metrics = suite.get("metrics")
        if not isinstance(suite_metrics, list) or not suite_metrics:
            errors.append(f"{where}: metrics must be a non-empty list")
        elif len(suite_metrics) != len(set(suite_metrics)):
            errors.append(f"{where}: metrics must be unique")
        else:
            for metric_id in suite_metrics:
                if metric_id not in metrics:
                    errors.append(f"{where}: unknown metric {metric_id!r}")
                elif metrics[metric_id].get("kind") != "measured":
                    errors.append(f"{where}: benchmark suites may only contain measured metrics")

    models = registry.get("models")
    if not isinstance(models, list):
        errors.append("models must be a list")
        models = []
    model_ids: set[str] = set()
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
        for field in ("name", "author", "architecture", "license"):
            if not isinstance(model.get(field), str) or not model[field]:
                errors.append(f"{where}: {field} is required")
        if model.get("status") not in MODEL_STATUSES:
            errors.append(f"{where}: invalid status")
        stems = model.get("stems")
        if not isinstance(stems, list) or not stems or not all(isinstance(x, str) for x in stems):
            errors.append(f"{where}: stems must be a non-empty string list")
            stems = []
        elif len(stems) != len(set(stems)):
            errors.append(f"{where}: stems must be unique")
        backends = model.get("backends")
        if not isinstance(backends, dict) or not backends:
            errors.append(f"{where}: backends must be a non-empty object")
        else:
            for backend, details in backends.items():
                if not isinstance(details, dict):
                    errors.append(f"{where}: backend {backend} must be an object")
                elif "tested" in details and not isinstance(details["tested"], bool):
                    errors.append(f"{where}: backend {backend}.tested must be boolean")

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
                benchmark_key = (suite_id, result.get("stem"))
                if benchmark_key in benchmark_keys:
                    errors.append(f"{result_where}: duplicate suite/stem result")
                benchmark_keys.add(benchmark_key)
                if suite_id not in suites:
                    errors.append(f"{result_where}: unknown suite {suite_id!r}")
                    suite_metrics = []
                else:
                    suite_metrics = suites[suite_id]["metrics"]
                if result.get("stem") not in stems:
                    errors.append(f"{result_where}: invalid stem")
                values = result.get("values")
                if not isinstance(values, dict) or not values:
                    errors.append(f"{result_where}: values must be a non-empty object")
                else:
                    for metric_id, value in values.items():
                        if metric_id not in suite_metrics:
                            errors.append(f"{result_where}: metric {metric_id!r} is not in suite")
                        if not isinstance(value, (int, float)) or isinstance(value, bool):
                            errors.append(f"{result_where}: {metric_id} must be numeric")
                if not valid_url(result.get("source")):
                    errors.append(f"{result_where}: HTTPS source is required")

        quality = model.get("quality")
        if not isinstance(quality, list):
            errors.append(f"{where}: quality must be a list")
        else:
            for observation_index, observation in enumerate(quality):
                observation_where = f"{where}.quality[{observation_index}]"
                if not isinstance(observation, dict):
                    errors.append(f"{observation_where}: must be an object")
                    continue
                if observation.get("stem") not in stems:
                    errors.append(f"{observation_where}: invalid stem")
                if observation.get("method") not in QUALITY_METHODS:
                    errors.append(f"{observation_where}: invalid method")
                confidence = observation.get("confidence")
                if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
                    errors.append(f"{observation_where}: confidence must be numeric")
                elif not 0 <= confidence <= 1:
                    errors.append(f"{observation_where}: confidence must be between 0 and 1")
                values = observation.get("values")
                if not isinstance(values, dict) or not values:
                    errors.append(f"{observation_where}: values must be a non-empty object")
                else:
                    for metric_id, value in values.items():
                        definition = metrics.get(metric_id)
                        if not definition or definition.get("kind") != "normalized":
                            errors.append(f"{observation_where}: {metric_id!r} is not normalized")
                            continue
                        if not isinstance(value, (int, float)) or isinstance(value, bool):
                            errors.append(f"{observation_where}: {metric_id} must be numeric")
                        elif not definition["min"] <= value <= definition["max"]:
                            errors.append(f"{observation_where}: {metric_id} is outside its range")
                if not valid_url(observation.get("source")):
                    errors.append(f"{observation_where}: HTTPS source is required")

        source_links = model.get("sources")
        if not isinstance(source_links, list) or not source_links:
            errors.append(f"{where}: sources must be a non-empty list")
        elif not all(valid_url(link) for link in source_links):
            errors.append(f"{where}: sources must contain HTTPS links")

    recommendations = registry.get("recommendations")
    if not isinstance(recommendations, dict) or not recommendations:
        errors.append("recommendations must be a non-empty object")
        recommendations = {}
    for stem, recommendation in recommendations.items():
        where = f"recommendations.{stem}"
        if not isinstance(recommendation, dict):
            errors.append(f"{where}: must be an object")
            continue
        model_id = recommendation.get("model")
        if model_id not in by_id:
            errors.append(f"{where}: unknown model {model_id!r}")
        else:
            model = by_id[model_id]
            if stem not in model.get("stems", []):
                errors.append(f"{where}: model does not produce {stem}")
            if model.get("status") != "recommended":
                errors.append(f"{where}: selected model must have recommended status")
        if not valid_date(recommendation.get("reviewed")):
            errors.append(f"{where}: reviewed must be YYYY-MM-DD")
        links = recommendation.get("sources")
        if not isinstance(links, list) or not links or not all(valid_url(link) for link in links):
            errors.append(f"{where}: sources must contain HTTPS links")

    watched = watched_sources.get("sources")
    if not isinstance(watched, list):
        errors.append("sources.json: sources must be a list")
    else:
        names: set[str] = set()
        for index, source in enumerate(watched):
            where = f"sources[{index}]"
            name = source.get("name") if isinstance(source, dict) else None
            if not isinstance(name, str) or not name:
                errors.append(f"{where}: name is required")
            elif name in names:
                errors.append(f"{where}: duplicate source name {name}")
            else:
                names.add(name)
            if not isinstance(source, dict) or not valid_url(source.get("url")):
                errors.append(f"{where}: HTTPS url is required")
            if isinstance(source, dict) and "fetch_url" in source and not valid_url(source["fetch_url"]):
                errors.append(f"{where}: fetch_url must be HTTPS")
            if not isinstance(source, dict) or not isinstance(source.get("enabled"), bool):
                errors.append(f"{where}: enabled must be boolean")

    if errors:
        print("Registry validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    benchmark_count = sum(len(model["benchmarks"]) for model in models)
    quality_count = sum(len(model["quality"]) for model in models)
    print(
        f"Registry valid: {len(models)} models, {len(recommendations)} recommendations, "
        f"{benchmark_count} benchmarks, {quality_count} quality observations"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
