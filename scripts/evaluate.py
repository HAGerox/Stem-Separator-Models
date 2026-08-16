#!/usr/bin/env python3
"""Compare every changed recommendation using exact backend output contracts."""

from __future__ import annotations

import html
import json
import os
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def normalized_outputs(details: dict[str, Any]) -> list[dict[str, str]]:
    outputs = []
    for item in details.get("outputs", []):
        if isinstance(item, str):
            outputs.append({"runtime_key": item, "capability": item})
        elif isinstance(item, dict):
            outputs.append(
                {"runtime_key": item["runtime_key"], "capability": item["capability"]}
            )
    return outputs


def model_backend(registry: dict, model_id: str, capability: str) -> tuple[str, str, str]:
    model = next(model for model in registry["models"] if model["id"] == model_id)
    for backend, reference_field in (
        ("audio_separator", "model_filename"),
        ("pymss", "catalog_id"),
    ):
        details = model.get("backends", {}).get(backend, {})
        matches = [
            output
            for output in normalized_outputs(details)
            if output["capability"] == capability
        ]
        if (
            details.get("state") in {"listed", "validated"}
            and details.get(reference_field)
            and len(matches) == 1
        ):
            return backend, details[reference_field], matches[0]["runtime_key"]
    raise RuntimeError(
        f"{model_id} has no evaluator-supported exact output contract for {capability}"
    )


def recommendation_capabilities(registry: dict, recommendation: dict, task: str) -> list[str]:
    if task != "multitrack":
        return [task]
    model = next(model for model in registry["models"] if model["id"] == recommendation["model"])
    decomposition = model.get("decompositions", {}).get(recommendation.get("decomposition"), {})
    outputs = decomposition.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        raise RuntimeError("Multitrack recommendation has no decomposition outputs")
    return outputs


def model_plan(
    registry: dict, model_id: str, capabilities: list[str]
) -> tuple[str, str, dict[str, str]]:
    plans = [model_backend(registry, model_id, capability) for capability in capabilities]
    backend_references = {(backend, reference) for backend, reference, _ in plans}
    if len(backend_references) != 1:
        raise RuntimeError(f"{model_id} cannot deliver the requested outputs in one backend run")
    backend, reference = next(iter(backend_references))
    return backend, reference, {
        capability: runtime_key
        for capability, (_, _, runtime_key) in zip(capabilities, plans, strict=True)
    }


def separate(track: Path, backend: str, model: str, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    if backend == "audio_separator":
        command = [
            "audio-separator",
            str(track),
            "--model_filename",
            model,
            "--output_dir",
            str(output),
            "--output_format",
            "WAV",
        ]
    elif backend == "pymss":
        command = [
            "pymss",
            "infer",
            model,
            "--input",
            str(track),
            "--output",
            str(output),
            "--format",
            "wav",
        ]
    else:
        raise RuntimeError(f"Unsupported evaluation backend: {backend}")
    subprocess.run(command, check=True)


def exact_output(directory: Path, runtime_key: str) -> Path:
    files = sorted(directory.rglob("*.wav"))
    key = runtime_key.casefold()
    matches = [
        path
        for path in files
        if path.stem.casefold() == key or f"({key})" in path.stem.casefold()
    ]
    if len(matches) != 1:
        names = ", ".join(path.name for path in files) or "none"
        raise RuntimeError(
            f"Expected one exact {runtime_key!r} output in {directory}, found "
            f"{len(matches)} among: {names}"
        )
    return matches[0]


def track_filename(track: object) -> str:
    if isinstance(track, str):
        return track
    if isinstance(track, dict) and isinstance(track.get("filename"), str):
        return track["filename"]
    raise RuntimeError("Each evaluation track must be a filename or an object with filename")


def safe_track_path(audio_dir: Path, filename: str) -> Path:
    relative = Path(filename)
    if relative.is_absolute() or ".." in relative.parts:
        raise RuntimeError(f"Unsafe evaluation track filename: {filename}")
    return audio_dir / relative


def changed_tasks(base: dict[str, Any], proposed: dict[str, Any]) -> list[str]:
    requested = [
        item.strip() for item in os.environ.get("STEMS", "").split(",") if item.strip()
    ]
    changes = [
        task
        for task in sorted(
            set(base.get("recommendations", {})) | set(proposed.get("recommendations", {}))
        )
        if base.get("recommendations", {}).get(task)
        != proposed.get("recommendations", {}).get(task)
    ]
    if requested:
        unknown = set(requested) - set(changes)
        if unknown:
            raise RuntimeError(
                "Requested tasks are not changed recommendations: " + ", ".join(unknown)
            )
        return requested
    return changes


def main() -> int:
    base = json.loads((ROOT / "registry.json").read_text(encoding="utf-8"))
    proposed_path = ROOT / os.environ.get("PROPOSED_REGISTRY", "proposed-registry.json")
    proposed = json.loads(proposed_path.read_text(encoding="utf-8"))
    tasks = changed_tasks(base, proposed)
    if not tasks:
        raise RuntimeError("The proposed registry has no recommendation changes")

    tracks_path = ROOT / os.environ.get("TRACKS_FILE", "evaluation/tracks.local.json")
    if not tracks_path.is_file():
        raise RuntimeError(
            f"Missing private evaluation manifest: {tracks_path}. "
            "Copy evaluation/tracks.json to evaluation/tracks.local.json and add private track filenames."
        )
    tracks = json.loads(tracks_path.read_text(encoding="utf-8"))["tracks"]
    if not tracks:
        raise RuntimeError(f"Private evaluation manifest has no tracks: {tracks_path}")
    audio_dir = Path(os.environ.get("AUDIO_DIR", "/opt/stem-registry/tracks"))
    output = ROOT / os.environ.get("OUTPUT_DIR", "evaluation/results/local")

    rows = []
    for task in tasks:
        current = base.get("recommendations", {}).get(task, {})
        proposed_recommendation = proposed.get("recommendations", {}).get(task, {})
        current_id = current.get("model")
        proposed_id = proposed_recommendation.get("model")
        if not proposed_id:
            continue
        current_capabilities = (
            recommendation_capabilities(base, current, task) if current_id else []
        )
        proposed_capabilities = recommendation_capabilities(
            proposed, proposed_recommendation, task
        )
        capabilities = list(dict.fromkeys(current_capabilities + proposed_capabilities))
        current_plan = model_plan(base, current_id, current_capabilities) if current_id else None
        proposed_backend, proposed_model, proposed_keys = model_plan(
            proposed, proposed_id, proposed_capabilities
        )
        for track_entry in tracks:
            filename = track_filename(track_entry)
            track = safe_track_path(audio_dir, filename)
            if not track.is_file():
                raise RuntimeError(f"Missing evaluation track: {track}")
            track_output = output / task / Path(filename).stem
            current_output = track_output / "current"
            proposed_output = track_output / "proposed"
            if current_plan:
                separate(track, current_plan[0], current_plan[1], current_output)
            separate(track, proposed_backend, proposed_model, proposed_output)
            for capability in capabilities:
                current_player = "—"
                if current_plan and capability in current_plan[2]:
                    current_stem = exact_output(current_output, current_plan[2][capability])
                    current_player = (
                        f'<code>{html.escape(current_id)}</code>'
                        f'<audio controls src="{html.escape(str(current_stem.relative_to(output)))}"></audio>'
                    )
                proposed_player = "—"
                if capability in proposed_keys:
                    proposed_stem = exact_output(proposed_output, proposed_keys[capability])
                    proposed_player = (
                        f'<code>{html.escape(proposed_id)}</code>'
                        f'<audio controls src="{html.escape(str(proposed_stem.relative_to(output)))}"></audio>'
                    )
                display_task = task if task != "multitrack" else f"multitrack / {capability}"
                rows.append(
                    "<tr>"
                    f"<td>{html.escape(display_task)}</td><td>{html.escape(filename)}</td>"
                    f"<td>{current_player}</td><td>{proposed_player}</td>"
                    "</tr>"
                )

    output.mkdir(parents=True, exist_ok=True)
    report = f"""<!doctype html><meta charset="utf-8"><title>Registry recommendation comparison</title>
<style>body{{font:16px system-ui;margin:2rem}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #bbb;padding:.75rem}}audio{{display:block;margin:.4rem 0}}</style>
<h1>Registry recommendation comparison</h1>
<p>Changed tasks: {html.escape(', '.join(tasks))}</p>
<table><tr><th>Task</th><th>Track</th><th>Current</th><th>Proposed</th></tr>{''.join(rows)}</table>"""
    (output / "index.html").write_text(report, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
