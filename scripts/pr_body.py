#!/usr/bin/env python3
"""Generate a structured PR body from a registry delta."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from evidence_policy import ORDINAL_RECOMMENDATION_POLICIES

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
    output = []
    for key in sorted(before.keys() | after.keys()):
        if stable(before.get(key)) == stable(after.get(key)):
            continue
        change = "Added" if key not in before else "Removed" if key not in after else "Updated"
        output.append((change, key))
    return output


def rows_changed_by_id(before: list[dict], after: list[dict]) -> list[tuple[str, dict]]:
    """Describe stable evidence records without rendering updates as remove/add."""

    before_rows = {row["id"]: row for row in before if isinstance(row.get("id"), str)}
    after_rows = {row["id"]: row for row in after if isinstance(row.get("id"), str)}
    output: list[tuple[str, dict]] = []
    for evidence_id in sorted(before_rows.keys() | after_rows.keys()):
        old = before_rows.get(evidence_id)
        new = after_rows.get(evidence_id)
        if old is not None and new is not None and stable(old) == stable(new):
            continue
        output.append(("Added" if old is None else "Removed" if new is None else "Updated", new or old))
    return output


def model_metadata(model: dict) -> dict:
    return {
        key: value
        for key, value in model.items()
        if key not in {"benchmarks", "semantic_evidence"}
    }


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


def task_model(recommendation: dict | None) -> str:
    if not recommendation or not recommendation.get("model"):
        return "—"
    decomposition = recommendation.get("decomposition")
    suffix = f" / `{decomposition}`" if decomposition else ""
    return f"`{recommendation['model']}`{suffix}"


def selection_signature(recommendation: dict | None) -> tuple[object, object]:
    recommendation = recommendation or {}
    return recommendation.get("model"), recommendation.get("decomposition")


def source_location(source: dict[str, Any]) -> str:
    location = source.get("location", {})
    kind = location.get("kind")
    if kind == "line_range":
        return f"lines {location.get('start')}–{location.get('end')}"
    if kind == "page":
        return f"page {location.get('page')}"
    return str(location.get("value", "—"))


def track_filename(track: object) -> str:
    if isinstance(track, str):
        return track
    if isinstance(track, dict) and isinstance(track.get("filename"), str):
        return track["filename"]
    raise RuntimeError("Each evaluation track must be a filename or an object with filename")


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

    benchmark_added: list[tuple[str, dict]] = []
    benchmark_removed: list[tuple[str, dict]] = []
    semantic_added: list[tuple[str, dict]] = []
    semantic_removed: list[tuple[str, dict]] = []
    for model_id in sorted(before_models.keys() | after_models.keys()):
        old_model = before_models.get(model_id, {})
        new_model = after_models.get(model_id, {})
        added, removed = rows_added_removed(
            old_model.get("benchmarks", []), new_model.get("benchmarks", [])
        )
        benchmark_added.extend((model_id, row) for row in added)
        benchmark_removed.extend((model_id, row) for row in removed)
        added, removed = rows_added_removed(
            old_model.get("semantic_evidence", []), new_model.get("semantic_evidence", [])
        )
        semantic_added.extend((model_id, row) for row in added)
        semantic_removed.extend((model_id, row) for row in removed)

    ordinal_changes = rows_changed_by_id(
        before.get("ordinal_evidence", []), after.get("ordinal_evidence", [])
    )

    before_recommendations = before.get("recommendations", {})
    after_recommendations = after.get("recommendations", {})
    changed_tasks = [
        task
        for task in sorted(before_recommendations.keys() | after_recommendations.keys())
        if stable(before_recommendations.get(task)) != stable(after_recommendations.get(task))
    ]
    selection_changed_tasks = [
        task
        for task in sorted(before_recommendations.keys() & after_recommendations.keys())
        if selection_signature(before_recommendations.get(task))
        != selection_signature(after_recommendations.get(task))
    ]
    baseline_replacement = before.get("schema") != after.get("schema") or (
        before.get("baseline") is not True and after.get("baseline") is True
    )
    maintenance_change = (
        before.get("generated_at") != after.get("generated_at")
        or stable(before.get("source_snapshots", {})) != stable(after.get("source_snapshots", {}))
        or (before.get("baseline") is True and after.get("baseline") is False)
    )
    if len(selection_changed_tasks) > 1 and not baseline_replacement:
        raise RuntimeError(
            "A PR may replace at most one existing recommendation selection: "
            + ", ".join(selection_changed_tasks)
        )
    recommendation_rows = []
    for task in changed_tasks:
        old = before_recommendations.get(task)
        new = after_recommendations.get(task)
        recommendation_rows.append(
            [
                task,
                task_model(old),
                task_model(new),
            ]
        )

    model_rows = []
    for change, model_ids, source in (
        ("Added", added_models, after_models),
        ("Updated", updated_models, after_models),
        ("Removed", removed_models, before_models),
    ):
        for model_id in model_ids:
            model = source[model_id]
            model_rows.append(
                [
                    change,
                    f"`{model_id}`",
                    model["status"],
                    ", ".join(model.get("tasks", model.get("stems", []))),
                    model.get("availability", {}).get("state", "legacy"),
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

    semantic_rows = []
    for change, entries in (("Added", semantic_added), ("Removed", semantic_removed)):
        for model_id, observation in entries:
            semantic_rows.append(
                [
                    change,
                    f"`{model_id}`",
                    observation["task"],
                    metric_values(observation["values"]),
                    str(observation["confidence"]),
                    source_link(observation["source"]),
                ]
            )

    ordinal_rows = []
    for change, observation in ordinal_changes:
        source = observation.get("source", {})
        snapshot_id = source.get("snapshot")
        snapshots = (
            before.get("source_snapshots", {})
            if change == "Removed"
            else after.get("source_snapshots", {})
        )
        snapshot = snapshots.get(snapshot_id, {})
        tier = snapshot.get("tiers", {}).get("qualitative", "—")
        ordinal_rows.append(
            [
                change,
                f"`{observation.get('id', '—')}`",
                str(observation.get("task", "—")),
                f"`{observation.get('context', '—')}`",
                f"`{observation.get('metric', '—')}`",
                f"`{observation.get('left', {}).get('model', '—')}`",
                str(observation.get("relation", "—")),
                f"`{observation.get('right', {}).get('model', '—')}`",
                str(observation.get("confidence", "—")),
                str(tier),
                source_link(source["entry_url"]) if source.get("entry_url") else "—",
                source_location(source),
                str(observation.get("summary", "—")),
            ]
        )
    ordinal_change_counts = {
        change: sum(item_change == change for item_change, unused in ordinal_changes)
        for change in ("Added", "Updated", "Removed")
    }
    ordinal_affected_tasks = sorted(
        {
            observation.get("task")
            for unused, observation in ordinal_changes
            if isinstance(observation.get("task"), str)
        }
    )

    metric_changes = changed_keys(
        before.get("metric_definitions", {}), after.get("metric_definitions", {})
    )
    suite_changes = changed_keys(
        before.get("benchmark_suites", {}), after.get("benchmark_suites", {})
    )
    tracks_path = ROOT / os.environ.get("TRACKS_FILE", "evaluation/tracks.local.json")
    tracks = (
        [track_filename(track) for track in load(tracks_path)["tracks"]]
        if tracks_path.is_file()
        else []
    )

    overview_rows = [
        ["Models", f"+{len(added_models)} / ~{len(updated_models)} / -{len(removed_models)}"],
        ["Measured results", f"+{len(benchmark_added)} / -{len(benchmark_removed)}"],
        ["Legacy semantic observations", f"+{len(semantic_added)} / -{len(semantic_removed)}"],
        [
            "Ordinal comparisons",
            f"+{ordinal_change_counts['Added']} / "
            f"~{ordinal_change_counts['Updated']} / -{ordinal_change_counts['Removed']}",
        ],
        ["Evidence-affected tasks", ", ".join(ordinal_affected_tasks) or "none"],
        ["Metric definitions", str(len(metric_changes))],
        ["Benchmark suites", str(len(suite_changes))],
        [
            "Code policy",
            ", ".join(sorted(ORDINAL_RECOMMENDATION_POLICIES)),
        ],
        [
            "Recommendation task",
            changed_tasks[0]
            if len(changed_tasks) == 1
            else f"{len(changed_tasks)} tasks"
            if changed_tasks
            else "unchanged",
        ],
        [
            "Selection change",
            selection_changed_tasks[0]
            if len(selection_changed_tasks) == 1
            else "baseline migration"
            if selection_changed_tasks
            else "unchanged",
        ],
    ]
    listening_required = bool(selection_changed_tasks) and not baseline_replacement
    if listening_required:
        overview_rows.append(
            ["Test tracks", "<br>".join(f"`{track}`" for track in tracks) or "public manifest not present"]
        )
        overview_rows.append(
            ["Listening artifact", f"[download]({args.artifact_url})" if args.artifact_url else "pending"]
        )

    lines = ["## Overview", ""]
    lines.extend(table(["Field", "Value"], overview_rows))
    lines.extend(["", "## Registry delta", "", "### Models", ""])
    lines.extend(table(["Change", "Model", "Status", "Tasks", "Availability"], model_rows))
    lines.extend(["", "### Measured benchmark results", ""])
    lines.extend(table(["Change", "Model", "Stem", "Suite", "Values", "Evidence"], benchmark_rows))
    lines.extend(["", "### Structured semantic evidence", ""])
    lines.extend(table(["Change", "Model", "Task", "Values", "Confidence", "Evidence"], semantic_rows))
    lines.extend(["", "### Ordinal evidence", ""])
    lines.extend(
        table(
            [
                "Change",
                "Evidence",
                "Task",
                "Context",
                "Metric",
                "Left",
                "Relation",
                "Right",
                "Confidence",
                "Tier",
                "Source",
                "Location",
                "Summary",
            ],
            ordinal_rows,
        )
    )
    lines.extend(["", "### Recommendations", ""])
    lines.extend(
        table(
            ["Task", "Current", "Proposed"],
            recommendation_rows,
        )
    )
    lines.extend(["", "## Listening comparison", ""])
    if listening_required:
        lines.append("- Task: " + f"`{selection_changed_tasks[0]}`")
        if tracks:
            lines.append("- Test tracks:")
            lines.extend(f"  - `{track}`" for track in tracks)
        else:
            lines.append("- Test tracks: public manifest not present")
        lines.append(
            f"- Artifact: [download comparison]({args.artifact_url})"
            if args.artifact_url
            else "- Artifact: pending"
        )
        lines.append(f"- [ ] Accept recommendation change for `{selection_changed_tasks[0]}`")
    else:
        lines.append(
            "Not required for this baseline replacement."
            if baseline_replacement
            else "Not required for this dated registry maintenance update."
            if maintenance_change
            else "Not required: no recommendation changed."
        )
    lines.extend(["", "## Checks", "", "- [x] `python3 scripts/validate.py`", ""])
    args.output.write_text("\n".join(lines), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
