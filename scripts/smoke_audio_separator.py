#!/usr/bin/env python3
"""Run trusted, exact-checkpoint Audio Separator admission smokes.

The PR is treated only as registry data. This module runs trusted code from the
base branch on a hosted runner; it never imports or executes code from the
proposed branch.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import struct
import subprocess
import tempfile
import threading
import urllib.request
import wave
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from smoke_policy import (
    ACCEPTED_SMOKE_FIXTURES,
    AUDIO_SEPARATOR_REVISION,
    CONFIG_SUFFIXES,
    SMOKE_FIXTURE,
    SMOKE_SCHEMA,
    TRUSTED_ARTIFACT_DELIVERY_SUFFIXES,
    TRUSTED_ARTIFACT_ORIGINS,
    WEIGHT_SUFFIXES,
    contract_sha256,
    smoke_evidence_errors,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_TOKEN = re.compile(r"_\(([^()]*)\)_[^/]+\.wav$", re.IGNORECASE)
_DOWNLOAD_LOCKS: dict[str, threading.Lock] = {}
_DOWNLOAD_LOCKS_GUARD = threading.Lock()


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def trusted_artifact_url(value: str, *, delivery: bool = False) -> bool:
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or parsed.username or parsed.password:
        return False
    if host in TRUSTED_ARTIFACT_ORIGINS:
        return True
    return delivery and any(host.endswith(suffix) for suffix in TRUSTED_ARTIFACT_DELIVERY_SUFFIXES)


def rich_fixture(path: Path, duration_seconds: float = 6.0) -> int:
    """Create deterministic stereo audio that exercises both separator channels."""

    sample_rate = 44100
    frame_count = round(sample_rate * duration_seconds)
    state = 0x13579BDF
    with wave.open(str(path), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        frames = bytearray()
        for index in range(frame_count):
            state = (1103515245 * state + 12345) & 0x7FFFFFFF
            noise = (state / 0x7FFFFFFF - 0.5) * 0.08
            time = index / sample_rate
            pulse = 0.28 if index % 5512 < 18 else 0.0
            envelope = 0.55 + 0.45 * math.sin(2 * math.pi * 0.73 * time)
            left = (
                0.26 * math.sin(2 * math.pi * 110 * time)
                + 0.19 * math.sin(2 * math.pi * 440 * time) * envelope
                + 0.12 * math.sin(2 * math.pi * (880 + 120 * time) * time)
                + noise
                + pulse
            )
            right = (
                0.24 * math.sin(2 * math.pi * 146.83 * time)
                + 0.17 * math.sin(2 * math.pi * 659.25 * time) * (1.0 - envelope / 2)
                + 0.10 * math.sin(2 * math.pi * (330 + 90 * time) * time)
                - noise
                - pulse / 2
            )
            frames.extend(
                struct.pack(
                    "<hh",
                    max(-32768, min(32767, round(left * 24000))),
                    max(-32768, min(32767, round(right * 24000))),
                )
            )
        output.writeframes(frames)
    return frame_count


def download_verified(artifact: dict[str, Any], cache_root: Path) -> Path:
    digest = artifact["sha256"]
    with _DOWNLOAD_LOCKS_GUARD:
        lock = _DOWNLOAD_LOCKS.setdefault(digest, threading.Lock())
    with lock:
        cached = cache_root / digest / artifact["name"]
        if cached.is_file() and sha256_file(cached) == digest:
            return cached
        cached.parent.mkdir(parents=True, exist_ok=True)
        partial = cached.with_suffix(cached.suffix + ".part")
        partial.unlink(missing_ok=True)
        if not trusted_artifact_url(artifact["url"]):
            raise RuntimeError(f"Untrusted artifact origin for {artifact['name']}")
        request = urllib.request.Request(
            artifact["url"], headers={"User-Agent": "stem-separator-smoke/1"}
        )
        with urllib.request.urlopen(request, timeout=120) as response, partial.open("wb") as output:
            if not trusted_artifact_url(response.geturl(), delivery=True):
                raise RuntimeError(f"Untrusted artifact delivery URL for {artifact['name']}")
            shutil.copyfileobj(response, output, length=1024 * 1024)
        actual = sha256_file(partial)
        if actual != digest:
            partial.unlink(missing_ok=True)
            raise RuntimeError(
                f"SHA-256 mismatch for {artifact['name']}: expected {digest}, got {actual}"
            )
        partial.replace(cached)
        return cached


def selected_backend_artifacts(model: dict[str, Any], backend: dict[str, Any]) -> list[dict[str, Any]]:
    requested = backend.get("artifact_names", [])
    by_name = {
        artifact.get("name"): artifact
        for artifact in model.get("availability", {}).get("artifacts", [])
        if isinstance(artifact, dict)
    }
    missing = [name for name in requested if name not in by_name]
    if missing:
        raise RuntimeError("Missing selected artifacts: " + ", ".join(missing))
    return [by_name[name] for name in requested]


def stage_model(
    model: dict[str, Any], backend: dict[str, Any], cache_root: Path, model_root: Path
) -> None:
    artifacts = selected_backend_artifacts(model, backend)
    weights = [item for item in artifacts if Path(item["name"]).suffix.lower() in WEIGHT_SUFFIXES]
    configs = [item for item in artifacts if Path(item["name"]).suffix.lower() in CONFIG_SUFFIXES]
    if len(weights) != 1 or len(configs) != 1:
        raise RuntimeError("Smoke admission requires exactly one checkpoint and one YAML config")
    model_filename = backend["model_filename"]
    runtime_config = f"{Path(model_filename).stem}.yaml"
    staged = {
        model_filename: download_verified(weights[0], cache_root),
        runtime_config: download_verified(configs[0], cache_root),
    }
    model_root.mkdir(parents=True, exist_ok=True)
    for runtime_name, source in staged.items():
        destination = model_root / runtime_name
        if destination.exists():
            destination.unlink()
        try:
            os.link(source, destination)
        except OSError:
            shutil.copy2(source, destination)


def output_token(path: Path) -> str | None:
    match = OUTPUT_TOKEN.search(path.name)
    return match.group(1) if match else None


def verify_wave(path: Path, expected_frames: int) -> dict[str, Any]:
    with wave.open(str(path), "rb") as audio:
        channels = audio.getnchannels()
        sample_rate = audio.getframerate()
        frames = audio.getnframes()
        width = audio.getsampwidth()
        payload = audio.readframes(frames)
    if channels != 2 or sample_rate != 44100:
        raise RuntimeError(f"Unexpected audio format for {path.name}: {channels}ch/{sample_rate}Hz")
    if abs(frames - expected_frames) > 2048:
        raise RuntimeError(
            f"Unexpected frame count for {path.name}: expected about {expected_frames}, got {frames}"
        )
    if width not in {2, 3, 4} or not payload:
        raise RuntimeError(f"Output contains no audio frames: {path.name}")
    return {
        "filename": path.name,
        "channels": channels,
        "sample_rate": sample_rate,
        "frames": frames,
        "sample_width": width,
        "nonzero_audio": any(payload),
    }


def smoke_model(
    model: dict[str, Any],
    audio_separator: Path,
    cache_root: Path,
    work_root: Path,
    timeout_seconds: int,
    fixture_source: Path | None = None,
    fixture_id: str = SMOKE_FIXTURE,
) -> dict[str, Any]:
    backend = model["backends"]["audio_separator"]
    model_root = work_root / "models"
    output_root = work_root / "outputs"
    output_root.mkdir(parents=True, exist_ok=True)
    stage_model(model, backend, cache_root, model_root)
    fixture = work_root / "synthetic-rich-mix.wav"
    if fixture_source is None:
        expected_frames = rich_fixture(fixture)
    else:
        shutil.copy2(fixture_source, fixture)
        with wave.open(str(fixture), "rb") as audio:
            if audio.getnchannels() != 2 or audio.getframerate() != 44100:
                raise RuntimeError("Smoke fixture must be stereo 44.1 kHz WAV")
            expected_frames = audio.getnframes()
    command = [
        str(audio_separator),
        str(fixture),
        "--model_filename",
        backend["model_filename"],
        "--model_file_dir",
        str(model_root),
        "--output_dir",
        str(output_root),
        "--output_format",
        "WAV",
        "--sample_rate",
        "44100",
        "--log_level",
        "info",
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    log_path = work_root / "audio-separator.log"
    log_path.write_text(completed.stdout + "\n" + completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(
            f"audio-separator exited {completed.returncode}; see {log_path.name}"
        )
    files_by_token: dict[str, Path] = {}
    for path in output_root.glob("*.wav"):
        token = output_token(path)
        if token:
            folded = token.casefold()
            if folded in files_by_token:
                raise RuntimeError(f"Duplicate runtime output token: {token}")
            files_by_token[folded] = path
    expected_tokens = sorted(output["runtime_key"] for output in backend["outputs"])
    missing = [token for token in expected_tokens if token.casefold() not in files_by_token]
    if missing:
        raise RuntimeError("Missing exact runtime outputs: " + ", ".join(missing))
    expected_folded = {token.casefold() for token in expected_tokens}
    unexpected = sorted(
        path.name for token, path in files_by_token.items() if token not in expected_folded
    )
    if unexpected:
        raise RuntimeError("Undeclared runtime outputs: " + ", ".join(unexpected))
    wave_reports = [
        {"runtime_key": token, **verify_wave(files_by_token[token.casefold()], expected_frames)}
        for token in expected_tokens
    ]
    return {
        "model": model["id"],
        "status": "passed",
        "contract_sha256": contract_sha256(model, backend),
        "fixture": fixture_id,
        "outputs": wave_reports,
        "log": str(log_path),
    }


def pending_models(
    base: dict[str, Any], proposed: dict[str, Any], all_pending: bool
) -> list[dict[str, Any]]:
    base_models = {model["id"]: model for model in base.get("models", [])}
    output = []
    for model in proposed.get("models", []):
        backend = model.get("backends", {}).get("audio_separator", {})
        is_pending = (
            backend.get("state") == "compatible_unvalidated"
            and backend.get("validated") is False
        )
        has_stale_smoke = (
            backend.get("state") == "validated"
            and backend.get("validated") is True
            and "smoke_validation" in backend
            and bool(smoke_evidence_errors(model, backend))
        )
        if not is_pending and not has_stale_smoke:
            continue
        before = base_models.get(model["id"], {}).get("backends", {}).get("audio_separator")
        if all_pending or before != backend:
            output.append(model)
    return sorted(output, key=lambda model: model["id"])


def promote(model: dict[str, Any], result: dict[str, Any]) -> None:
    backend = model["backends"]["audio_separator"]
    backend["state"] = "validated"
    backend["validated"] = True
    backend["smoke_validation"] = {
        "schema": SMOKE_SCHEMA,
        "kind": "exact_checkpoint_smoke",
        "runtime": "python-audio-separator",
        "runtime_revision": AUDIO_SEPARATOR_REVISION,
        "fixture": result.get("fixture", SMOKE_FIXTURE),
        "contract_sha256": result["contract_sha256"],
        "outputs": sorted(output["runtime_key"] for output in backend["outputs"]),
        "sample_rate": 44100,
        "channels": 2,
        "validated_at": datetime.now(timezone.utc).date().isoformat(),
    }


def run(args: argparse.Namespace) -> int:
    if args.fixture_id not in ACCEPTED_SMOKE_FIXTURES:
        raise RuntimeError(f"Untrusted smoke fixture id: {args.fixture_id}")
    if args.fixture_file is None and args.fixture_id != SMOKE_FIXTURE:
        raise RuntimeError("A non-default smoke fixture id requires --fixture-file")
    base = load(args.base_registry)
    proposed = load(args.registry)
    selected = pending_models(base, proposed, args.all_pending)
    report: dict[str, Any] = {
        "schema": 1,
        "runtime_revision": AUDIO_SEPARATOR_REVISION,
        "fixture": args.fixture_id,
        "models": [],
    }
    by_id = {model["id"]: model for model in proposed.get("models", [])}
    args.report_dir.mkdir(parents=True, exist_ok=True)
    def validate(model: dict[str, Any]) -> dict[str, Any]:
        model_work = args.report_dir / model["id"]
        if model_work.exists():
            shutil.rmtree(model_work)
        model_work.mkdir(parents=True)
        try:
            return smoke_model(
                model,
                args.audio_separator,
                args.cache_dir,
                model_work,
                args.timeout_seconds,
                args.fixture_file,
                args.fixture_id,
            )
        except Exception as error:  # Every model must leave a report for the PR.
            return {"model": model["id"], "status": "failed", "error": str(error)}

    results: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = {executor.submit(validate, model): model["id"] for model in selected}
        for future in as_completed(futures):
            model_id = futures[future]
            results[model_id] = future.result()
            print(f"{results[model_id]['status']}: {model_id}", flush=True)
    for model in selected:
        result = results[model["id"]]
        if result["status"] == "passed":
            promote(by_id[model["id"]], result)
        report["models"].append(result)
    report["passed"] = sum(item["status"] == "passed" for item in report["models"])
    report["failed"] = sum(item["status"] == "failed" for item in report["models"])
    write_json(args.output_registry, proposed)
    write_json(args.report_dir / "summary.json", report)
    if args.summary_output:
        lines = [
            "## Python Audio Separator smoke validation",
            "",
            f"Runtime revision: `{AUDIO_SEPARATOR_REVISION}`",
            f"Passed: {report['passed']} · Failed: {report['failed']}",
            "",
        ]
        for item in report["models"]:
            icon = "✅" if item["status"] == "passed" else "❌"
            detail = "exact outputs verified" if item["status"] == "passed" else item["error"]
            lines.append(f"- {icon} `{item['model']}` — {detail}")
        if not report["models"]:
            lines.append("No compatible, unvalidated models require a smoke test.")
        args.summary_output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


def verify_transitions(args: argparse.Namespace) -> int:
    base = load(args.base_registry)
    proposed = load(args.registry)
    base_models = {model["id"]: model for model in base.get("models", [])}
    errors = []
    for model in proposed.get("models", []):
        backend = model.get("backends", {}).get("audio_separator", {})
        if backend.get("state") != "validated" or backend.get("validated") is not True:
            continue
        before = base_models.get(model["id"], {}).get("backends", {}).get("audio_separator", {})
        contract_changed = (
            not before
            or before.get("state") != "validated"
            or contract_sha256(base_models.get(model["id"], model), before)
            != contract_sha256(model, backend)
        )
        trusted_evidence_exists = (
            "smoke_validation" in before or "smoke_validation" in backend
        )
        if contract_changed or trusted_evidence_exists:
            errors.extend(
                f"models.{model['id']}.backends.audio_separator: {error}"
                for error in smoke_evidence_errors(model, backend)
            )
    if errors:
        print("\n".join(f"ERROR: {error}" for error in errors))
        return 1
    print("Audio Separator validation transitions are backed by trusted smoke evidence.")
    return 0


def verify_promotions(args: argparse.Namespace) -> int:
    """Require runner output to differ only by successful smoke promotions."""

    original = load(args.registry)
    promoted = load(args.promoted_registry)
    normalized = deepcopy(promoted)
    original_models = {model["id"]: model for model in original.get("models", [])}
    errors = []
    for model in normalized.get("models", []):
        before_model = original_models.get(model.get("id"))
        if not before_model:
            continue
        before = before_model.get("backends", {}).get("audio_separator", {})
        after = model.get("backends", {}).get("audio_separator", {})
        is_promotion = (
            before.get("state") == "compatible_unvalidated"
            and before.get("validated") is False
            and after.get("state") == "validated"
            and after.get("validated") is True
        )
        is_revalidation = (
            before.get("state") == "validated"
            and before.get("validated") is True
            and after.get("state") == "validated"
            and after.get("validated") is True
            and "smoke_validation" in before
            and bool(smoke_evidence_errors(before_model, before))
        )
        if not is_promotion and not is_revalidation:
            continue
        if contract_sha256(before_model, before) != contract_sha256(model, after):
            errors.append(f"models.{model['id']}: smoke promotion changed its runtime contract")
        errors.extend(
            f"models.{model['id']}.backends.audio_separator: {error}"
            for error in smoke_evidence_errors(model, after)
        )
        if is_promotion:
            after["state"] = before["state"]
            after["validated"] = before["validated"]
            after.pop("smoke_validation", None)
        else:
            after["smoke_validation"] = before["smoke_validation"]
    if normalized != original:
        errors.append("smoke runner output contains changes other than validated backend promotions")
    if errors:
        print("\n".join(f"ERROR: {error}" for error in errors))
        return 1
    print("Smoke runner output contains only trusted backend promotions.")
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    commands = root.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run")
    run_parser.add_argument("--base-registry", type=Path, required=True)
    run_parser.add_argument("--registry", type=Path, required=True)
    run_parser.add_argument("--output-registry", type=Path, required=True)
    run_parser.add_argument("--audio-separator", type=Path, required=True)
    run_parser.add_argument("--cache-dir", type=Path, required=True)
    run_parser.add_argument("--report-dir", type=Path, required=True)
    run_parser.add_argument("--summary-output", type=Path)
    run_parser.add_argument("--timeout-seconds", type=int, default=1800)
    run_parser.add_argument("--jobs", type=int, default=1)
    run_parser.add_argument("--fixture-file", type=Path)
    run_parser.add_argument("--fixture-id", default=SMOKE_FIXTURE)
    run_parser.add_argument("--all-pending", action="store_true")
    verify = commands.add_parser("verify-transitions")
    verify.add_argument("--base-registry", type=Path, required=True)
    verify.add_argument("--registry", type=Path, required=True)
    promotions = commands.add_parser("verify-promotions")
    promotions.add_argument("--registry", type=Path, required=True)
    promotions.add_argument("--promoted-registry", type=Path, required=True)
    return root


def main() -> int:
    args = parser().parse_args()
    if args.command == "run":
        return run(args)
    if args.command == "verify-transitions":
        return verify_transitions(args)
    return verify_promotions(args)


if __name__ == "__main__":
    raise SystemExit(main())
