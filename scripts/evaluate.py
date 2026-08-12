#!/usr/bin/env python3
"""Compare the current and proposed recommendation using audio-separator."""

from __future__ import annotations

import html
import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def model_filename(registry: dict, model_id: str) -> str:
    model = next(model for model in registry["models"] if model["id"] == model_id)
    try:
        return model["backends"]["audio_separator"]["model_filename"]
    except KeyError as error:
        raise RuntimeError(f"{model_id} has no audio_separator model filename") from error


def separate(track: Path, model: str, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "audio-separator",
            str(track),
            "--model_filename",
            model,
            "--output_dir",
            str(output),
            "--output_format",
            "WAV",
        ],
        check=True,
    )


def main() -> int:
    stem = os.environ["STEM"]
    base = json.loads((ROOT / "registry.json").read_text(encoding="utf-8"))
    proposed_path = ROOT / os.environ.get("PROPOSED_REGISTRY", "proposed-registry.json")
    proposed = json.loads(proposed_path.read_text(encoding="utf-8"))
    current_id = base["recommendations"][stem]["model"]
    proposed_id = proposed["recommendations"][stem]["model"]
    if current_id == proposed_id:
        raise RuntimeError(f"The PR does not change the {stem} recommendation")

    tracks = json.loads((ROOT / "evaluation/tracks.json").read_text(encoding="utf-8"))["tracks"]
    audio_dir = Path(os.environ.get("AUDIO_DIR", "/opt/stem-registry/tracks"))
    output = ROOT / os.environ.get("OUTPUT_DIR", "evaluation/results/local")
    current_filename = model_filename(base, current_id)
    proposed_filename = model_filename(proposed, proposed_id)

    rows = []
    for filename in tracks:
        track = audio_dir / filename
        if not track.is_file():
            raise RuntimeError(f"Missing evaluation track: {track}")
        track_output = output / Path(filename).stem
        separate(track, current_filename, track_output / "current")
        separate(track, proposed_filename, track_output / "proposed")
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
