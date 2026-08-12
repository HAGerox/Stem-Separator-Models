#!/usr/bin/env python3
"""Validate the small, maintainer-authored registry without dependencies."""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
STATUSES = {"recommended", "experimental", "deprecated"}


def load(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def valid_url(value: object) -> bool:
    return isinstance(value, str) and urlparse(value).scheme == "https"


def main() -> int:
    errors: list[str] = []
    registry_path = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "registry.json"
    registry = load(registry_path)
    sources = load(ROOT / "sources.json")

    if registry.get("schema") != 1:
        errors.append("registry.json: schema must be 1")
    if sources.get("schema") != 1:
        errors.append("sources.json: schema must be 1")

    models = registry.get("models")
    if not isinstance(models, list):
        errors.append("registry.json: models must be a list")
        models = []

    ids: set[str] = set()
    by_id: dict[str, dict] = {}
    for index, model in enumerate(models):
        where = f"models[{index}]"
        model_id = model.get("id")
        if not isinstance(model_id, str) or not ID.fullmatch(model_id):
            errors.append(f"{where}: invalid id")
            continue
        if model_id in ids:
            errors.append(f"{where}: duplicate id {model_id}")
        ids.add(model_id)
        by_id[model_id] = model
        for field in ("name", "author", "architecture", "license"):
            if not isinstance(model.get(field), str) or not model[field]:
                errors.append(f"{where}: {field} must be a non-empty string")
        if model.get("status") not in STATUSES:
            errors.append(f"{where}: invalid status")
        stems = model.get("stems")
        if not isinstance(stems, list) or not stems or not all(isinstance(x, str) for x in stems):
            errors.append(f"{where}: stems must be a non-empty string list")
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
        evidence = model.get("sources")
        if not isinstance(evidence, list) or not evidence:
            errors.append(f"{where}: at least one source is required")
        else:
            for source in evidence:
                if not isinstance(source, dict) or not valid_url(source.get("url")):
                    errors.append(f"{where}: every source requires an HTTPS url")

    recommendations = registry.get("recommendations")
    if not isinstance(recommendations, dict) or not recommendations:
        errors.append("registry.json: recommendations must be a non-empty object")
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
        if not isinstance(recommendation.get("reason"), str) or not recommendation["reason"]:
            errors.append(f"{where}: reason is required")
        try:
            date.fromisoformat(recommendation.get("reviewed", ""))
        except (TypeError, ValueError):
            errors.append(f"{where}: reviewed must be YYYY-MM-DD")
        links = recommendation.get("sources")
        if not isinstance(links, list) or not links or not all(valid_url(link) for link in links):
            errors.append(f"{where}: sources must contain HTTPS links")

    watched = sources.get("sources")
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
            if not isinstance(source, dict) or not isinstance(source.get("enabled"), bool):
                errors.append(f"{where}: enabled must be boolean")

    if errors:
        print("Registry validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"Registry valid: {len(models)} models, {len(recommendations)} recommendations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
