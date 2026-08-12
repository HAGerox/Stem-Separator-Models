#!/usr/bin/env python3
"""Generate a structured PR body from an app-registry delta."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def registry_from_ref(ref: str) -> dict[str, Any]:
    content = subprocess.check_output(["git", "show", f"{ref}:registry.json"], text=True)
    return json.loads(content)


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def stable(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def rows_added_removed(before: list[dict], after: list[dict]) -> tuple[list[dict], list[dict]]:
    before_rows = {stable(row): row for row in before}
    after_rows = {stable(row): row for row in after}
    added = [after_rows[key] for key in sorted(after_rows.keys() - before_rows.keys())]
    removed = [before_rows[key] for key in sorted(before_rows.keys() - after_rows.keys())]
    return added, removed


def changed_keys(before: dict, after: dict) -> list[tuple[str, str]]:
    rows = []
    for key in sorted(before.keys() | after.keys()):
        if stable(before.get(key)) != stable(after.get(key)):
            if key not in before:
                change = "Added"
            elif key not in after:
                change = "Removed"
            else:
                change = "Updated"
            rows.append((change, key))
    return rows


def model_metadata(model: dict) -> dict:
    return {key: value for key, value in model.items() if key not in {"benchmarks", "quality"}}


def metric_values(values: dict[str, Any]) -> str:
    return ", ".join(f"`{key}`={value}" for key, value in sorted(values.items()))


def source_link(url: str) -> str:
    return f"[source]({url})"


def table(headers: list[str], rows: list[list[str]], empty: str = "None") -> list[str]:
    if not rows:
        return [empty]
    output = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    output.extend("| " + " | ".join(row) + " |" for row in rows)
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-ref", default="origin/main")
    parser.add_argument("--registry", type=Path, default=ROOT / "registry.json")
    parser.add_argument("--output", type=Path, default=ROOT / "PR_BODY.md")
    parser.add_argument("--artifact-url")
    args = parser.parse_args()

    before = registry_from_ref(args.base_ref)
    after = load(args.registry)
    before_models = {model["id"]: model for model in before["models"]}
    after_models = {model["id"]: model for model in after["models"]}
    added_models = sorted(after_models.keys() - before_models.keys())
    removed_models = sorted(before_models.keys() - after_models.keys())
    updated_models = sorted(
        model_id
        for model_id in before_models.keys() & after_models.keys()
        if stable(model_metadata(before_models[model_id]))
        != stable(model_metadata(after_models[model_id]))
    )
    metric_changes = changed_keys(
        before.get("metric_definitions", {}), after.get("metric_definitions", {})
    )
    suite_changes = changed_keys(
        before.get("benchmark_suites", {}), after.get("benchmark_suites", {})
    )

    benchmark_added: list[tuple[str, dict]] = []
    benchmark_removed: list[tuple[str, dict]] = []
    quality_added: list[tuple[str, dict]] = []
    quality_removed: list[tuple[str, dict]] = []
    for model_id in sorted(before_models.keys() | after_models.keys()):
        old_model = before_models.get(model_id, {})
        new_model = after_models.get(model_id, {})
        added, removed = rows_added_removed(
            old_model.get("benchmarks", []), new_model.get("benchmarks", [])
        )
        benchmark_added.extend((model_id, row) for row in added)
        benchmark_removed.extend((model_id, row) for row in removed)
        added, removed = rows_added_removed(old_model.get("quality", []), new_model.get("quality", []))
        quality_added.extend((model_id, row) for row in added)
        quality_removed.extend((model_id, row) for row in removed)

    recommendation_rows: list[list[str]] = []
    changed_stems = []
    before_recommendations = before["recommendations"]
    after_recommendations = after["recommendations"]
    for stem in sorted(before_recommendations.keys() | after_recommendations.keys()):
        old = before_recommendations.get(stem)
        new = after_recommendations.get(stem)
        old_model = old.get("model") if old else None
        new_model = new.get("model") if new else None
        if old_model != new_model:
            changed_stems.append(stem)
            recommendation_rows.append(
                [stem, f"`{old_model}`" if old_model else "—", f"`{new_model}`" if new_model else "—"]
            )
    if len(changed_stems) > 1:
        raise RuntimeError("Recommendation PRs must change no more than one stem")

    model_rows = []
    for model_id in added_models:
        model = after_models[model_id]
        model_rows.append(["Added", f"`{model_id}`", model["status"], ", ".join(model["stems"])])
    for model_id in updated_models:
        model = after_models[model_id]
        model_rows.append(["Updated", f"`{model_id}`", model["status"], ", ".join(model["stems"])])
    for model_id in removed_models:
        model = before_models[model_id]
        model_rows.append(["Removed", f"`{model_id}`", model["status"], ", ".join(model["stems"])])

    definition_rows = [[change, f"`{definition_id}`"] for change, definition_id in metric_changes]
    suite_rows = []
    for change, suite_id in suite_changes:
        suite = after.get("benchmark_suites", {}).get(suite_id) or before["benchmark_suites"][suite_id]
        suite_rows.append(
            [
                change,
                f"`{suite_id}`",
                "yes" if suite["standardized"] else "no",
                source_link(suite["protocol"]),
            ]
        )

    benchmark_rows = []
    for change, entries in (("Added", benchmark_added), ("Removed", benchmark_removed)):
        for model_id, result in entries:
            benchmark_rows.append(
                [
                    change,
                    f"`{model_id}`",
                    result["stem"],
                    f"`{result['suite']}`",
                    metric_values(result["values"]),
                    source_link(result["source"]),
                ]
            )

    quality_rows = []
    for change, entries in (("Added", quality_added), ("Removed", quality_removed)):
        for model_id, observation in entries:
            quality_rows.append(
                [
                    change,
                    f"`{model_id}`",
                    observation["stem"],
                    observation["method"],
                    metric_values(observation["values"]),
                    str(observation["confidence"]),
                    source_link(observation["source"]),
                ]
            )

    tracks = load(ROOT / "evaluation/tracks.json")["tracks"]
    overview_rows = [
        ["Models", f"+{len(added_models)} / ~{len(updated_models)} / -{len(removed_models)}"],
        ["Metric definitions", str(len(metric_changes))],
        ["Benchmark suites", str(len(suite_changes))],
        ["Benchmarks", f"+{len(benchmark_added)} / -{len(benchmark_removed)}"],
        ["Quality observations", f"+{len(quality_added)} / -{len(quality_removed)}"],
        ["Recommendation", changed_stems[0] if changed_stems else "unchanged"],
    ]
    if changed_stems:
        overview_rows.append(["Test files", "<br>".join(f"`{filename}`" for filename in tracks)])
        overview_rows.append(
            [
                "Comparison artifact",
                f"[download]({args.artifact_url})" if args.artifact_url else "pending",
            ]
        )
    lines = ["## Overview", ""]
    lines.extend(table(["Field", "Value"], overview_rows))
    lines.extend(["", "## Registry delta", "", "### Models", ""])
    lines.extend(table(["Change", "Model", "Status", "Stems"], model_rows))
    lines.extend(["", "### Metric definitions", ""])
    lines.extend(table(["Change", "Metric"], definition_rows))
    lines.extend(["", "### Benchmark suites", ""])
    lines.extend(table(["Change", "Suite", "Standardized", "Protocol"], suite_rows))
    lines.extend(["", "### Standardized and reported benchmarks", ""])
    lines.extend(
        table(
            ["Change", "Model", "Stem", "Suite", "Values", "Evidence"],
            benchmark_rows,
        )
    )
    lines.extend(["", "### Normalized quality observations", ""])
    lines.extend(
        table(
            ["Change", "Model", "Stem", "Method", "Values", "Confidence", "Evidence"],
            quality_rows,
        )
    )
    lines.extend(["", "### Recommendations", ""])
    lines.extend(table(["Stem", "Current", "Proposed"], recommendation_rows))
    lines.extend(["", "## Listening comparison", ""])
    if changed_stems:
        lines.append(f"- Stem: `{changed_stems[0]}`")
        lines.append("- Test files:")
        lines.extend(f"  - `{filename}`" for filename in tracks)
        if args.artifact_url:
            lines.append(f"- Artifact: [download comparison]({args.artifact_url})")
        else:
            lines.append("- Artifact: pending")
    else:
        lines.append("Not required: no recommendation changed.")
    lines.extend(["", "## Checks", "", "- [x] `python3 scripts/validate.py`", ""])
    args.output.write_text("\n".join(lines), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
