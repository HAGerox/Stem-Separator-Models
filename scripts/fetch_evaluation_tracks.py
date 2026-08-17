#!/usr/bin/env python3
"""Fetch and prepare the public, hash-pinned listening fixtures."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ALLOWED_HOSTS = {"ccmixter.org", "www.ccmixter.org"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def validated_track(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError("Each evaluation track must be an object")
    required_strings = (
        "filename",
        "source_filename",
        "source_url",
        "source_sha256",
        "source_page",
        "title",
        "artist",
        "license",
        "license_url",
    )
    for field in required_strings:
        if not isinstance(value.get(field), str) or not value[field].strip():
            raise RuntimeError(f"Evaluation track is missing {field}")
    for field in ("filename", "source_filename"):
        path = Path(value[field])
        if path.is_absolute() or ".." in path.parts or len(path.parts) != 1:
            raise RuntimeError(f"Unsafe evaluation track {field}: {value[field]}")
    parsed = urlparse(value["source_url"])
    if parsed.scheme != "https" or (parsed.hostname or "").lower() not in ALLOWED_HOSTS:
        raise RuntimeError(f"Untrusted evaluation source: {value['source_url']}")
    if len(value["source_sha256"]) != 64:
        raise RuntimeError("Evaluation source SHA-256 must contain 64 hex characters")
    try:
        int(value["source_sha256"], 16)
    except ValueError as error:
        raise RuntimeError("Evaluation source SHA-256 is not hexadecimal") from error
    start = value.get("start_seconds")
    duration = value.get("duration_seconds")
    if not isinstance(start, (int, float)) or start < 0:
        raise RuntimeError("Evaluation track start_seconds must be non-negative")
    if not isinstance(duration, (int, float)) or not 5 <= duration <= 90:
        raise RuntimeError("Evaluation track duration_seconds must be between 5 and 90")
    return value


def download(track: dict[str, Any], cache_dir: Path) -> Path:
    destination = cache_dir / track["source_sha256"] / track["source_filename"]
    if destination.is_file() and sha256_file(destination) == track["source_sha256"]:
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    partial.unlink(missing_ok=True)
    request = urllib.request.Request(
        track["source_url"],
        headers={
            "User-Agent": "Mozilla/5.0 stem-separator-evaluation/1",
            "Referer": track["source_page"],
        },
    )
    with urllib.request.urlopen(request, timeout=120) as response, partial.open("wb") as output:
        shutil.copyfileobj(response, output, length=1024 * 1024)
    actual = sha256_file(partial)
    if actual != track["source_sha256"]:
        partial.unlink(missing_ok=True)
        raise RuntimeError(
            f"SHA-256 mismatch for {track['title']}: expected "
            f"{track['source_sha256']}, got {actual}"
        )
    partial.replace(destination)
    return destination


def render(source: Path, track: dict[str, Any], destination: Path, ffmpeg: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=destination.parent, suffix=".wav", delete=False
    ) as temporary:
        partial = Path(temporary.name)
    try:
        subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                str(track["start_seconds"]),
                "-t",
                str(track["duration_seconds"]),
                "-i",
                str(source),
                "-ar",
                "44100",
                "-ac",
                "2",
                "-c:a",
                "pcm_s16le",
                str(partial),
            ],
            check=True,
        )
        partial.replace(destination)
    finally:
        partial.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    tracks = manifest.get("tracks")
    if not isinstance(tracks, list) or not tracks:
        raise RuntimeError("Evaluation manifest must contain at least one track")
    for raw_track in tracks:
        track = validated_track(raw_track)
        source = download(track, args.cache_dir)
        render(source, track, args.output_dir / track["filename"], args.ffmpeg)
        print(f"Prepared {track['filename']}: {track['title']} by {track['artist']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
