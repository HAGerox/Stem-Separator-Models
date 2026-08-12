#!/usr/bin/env python3
"""Compare the current and proposed recommendation using audio-separator."""

from __future__ import annotations

import html
import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def model_backend(registry: dict, model_id: str) -> tuple[str, str]:
    model = next(model for model in registry["models"] if model["id"] == model_id)
    audio_separator = model.get("backends", {}).get("audio_separator", {})
    if audio_separator.get("state") in {"listed", "validated"} and audio_separator.get(
        "model_filename"
    ):
        return "audio_separator", audio_separator["model_filename"]
    pymss = model.get("backends", {}).get("pymss", {})
    if pymss.get("state") in {"listed", "validated"} and pymss.get("catalog_id"):
        return "pymss", pymss["catalog_id"]
    raise RuntimeError(f"{model_id} has no evaluator-supported listed backend")


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


def main() -> int:
    stem = os.environ["STEM"]
    base = json.loads((ROOT / "registry.json").read_text(encoding="utf-8"))
    proposed_path = ROOT / os.environ.get("PROPOSED_REGISTRY", "proposed-registry.json")
    proposed = json.loads(proposed_path.read_text(encoding="utf-8"))
    current_id = base["recommendations"][stem].get("model")
    proposed_id = proposed["recommendations"][stem].get("model")
    if not current_id or not proposed_id:
        raise RuntimeError(f"Both registries need a model recommendation for {stem}")
    if current_id == proposed_id:
        raise RuntimeError(f"The PR does not change the {stem} recommendation")

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
    current_backend, current_model = model_backend(base, current_id)
    proposed_backend, proposed_model = model_backend(proposed, proposed_id)

    rows = []
    for track_entry in tracks:
        filename = track_filename(track_entry)
        track = safe_track_path(audio_dir, filename)
        if not track.is_file():
            raise RuntimeError(f"Missing evaluation track: {track}")
        track_output = output / Path(filename).stem
        separate(track, current_backend, current_model, track_output / "current")
        separate(track, proposed_backend, proposed_model, track_output / "proposed")
        current_files = sorted((track_output / "current").glob("*.wav"))
        proposed_files = sorted((track_output / "proposed").glob("*.wav"))
        current_stem = [path for path in current_files if stem.lower() in path.name.lower()] or current_files
        proposed_stem = [path for path in proposed_files if stem.lower() in path.name.lower()] or proposed_files
        current_players = "".join(
            f'<audio controls src="{html.escape(str(path.relative_to(output)))}"></audio>'
            for path in current_stem
        )
        proposed_players = "".join(
            f'<audio controls src="{html.escape(str(path.relative_to(output)))}"></audio>'
            for path in proposed_stem
        )
        rows.append(
            f"<tr><td>{html.escape(filename)}</td><td>{current_players}</td><td>{proposed_players}</td></tr>"
        )

    output.mkdir(parents=True, exist_ok=True)
    report = f"""<!doctype html><meta charset="utf-8"><title>{html.escape(stem)} comparison</title>
<style>body{{font:16px system-ui;margin:2rem}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #bbb;padding:.75rem}}audio{{display:block;margin:.4rem 0}}</style>
<h1>{html.escape(stem)} recommendation comparison</h1>
<p>Current: <code>{html.escape(current_id)}</code><br>Proposed: <code>{html.escape(proposed_id)}</code></p>
<table><tr><th>Track</th><th>Current</th><th>Proposed</th></tr>{''.join(rows)}</table>"""
    (output / "index.html").write_text(report, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
