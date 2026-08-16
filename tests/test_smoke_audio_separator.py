from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
import wave
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
import sys

sys.path.insert(0, str(SCRIPTS))

from smoke_audio_separator import (  # noqa: E402
    promote,
    pending_models,
    smoke_model,
    verify_wave,
    verify_promotions,
    verify_transitions,
)
from smoke_policy import contract_sha256, smoke_evidence_errors  # noqa: E402
from evaluate import changed_tasks  # noqa: E402


class AudioSeparatorSmokeTests(unittest.TestCase):
    def model(self) -> dict:
        return {
            "id": "test-model",
            "availability": {
                "artifacts": [
                    {
                        "name": "source.ckpt",
                        "url": "https://example.com/source.ckpt",
                        "sha256": "a" * 64,
                    },
                    {
                        "name": "source.yaml",
                        "url": "https://example.com/source.yaml",
                        "sha256": "b" * 64,
                    },
                ]
            },
            "backends": {
                "audio_separator": {
                    "state": "compatible_unvalidated",
                    "validated": False,
                    "model_filename": "runtime.ckpt",
                    "artifact_names": ["source.ckpt", "source.yaml"],
                    "outputs": [
                        {"runtime_key": "Alpha", "capability": "alpha"},
                        {"runtime_key": "beta", "capability": "beta"},
                    ],
                }
            },
        }

    def test_fake_runtime_verifies_exact_outputs_and_promotes(self) -> None:
        model = self.model()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoint = root / "source.ckpt"
            config = root / "source.yaml"
            checkpoint.write_bytes(b"checkpoint")
            config.write_text("model: {}\n", encoding="utf-8")
            executable = root / "audio-separator"
            executable.write_text(
                """#!/usr/bin/env python3
import argparse, pathlib, shutil
p=argparse.ArgumentParser()
p.add_argument('input')
p.add_argument('--model_filename')
p.add_argument('--model_file_dir')
p.add_argument('--output_dir')
p.add_argument('--output_format')
p.add_argument('--sample_rate')
p.add_argument('--log_level')
a=p.parse_args()
out=pathlib.Path(a.output_dir); out.mkdir(parents=True, exist_ok=True)
stem=pathlib.Path(a.model_filename).stem
for token in ('Alpha', 'beta'):
    shutil.copy2(a.input, out / f'synthetic-rich-mix_({token})_{stem}.wav')
""",
                encoding="utf-8",
            )
            executable.chmod(0o755)

            def cached(artifact: dict, unused_cache: Path) -> Path:
                return checkpoint if artifact["name"].endswith(".ckpt") else config

            with patch("smoke_audio_separator.download_verified", side_effect=cached):
                result = smoke_model(model, executable, root / "cache", root / "work", 30)
            self.assertEqual(result["status"], "passed")
            self.assertEqual(
                [item["runtime_key"] for item in result["outputs"]], ["Alpha", "beta"]
            )
            promote(model, result)
            backend = model["backends"]["audio_separator"]
            self.assertEqual(backend["state"], "validated")
            self.assertEqual(smoke_evidence_errors(model, backend), [])

    def test_transition_verifier_rejects_manual_promotion(self) -> None:
        base_model = self.model()
        proposed_model = deepcopy(base_model)
        backend = proposed_model["backends"]["audio_separator"]
        backend["state"] = "validated"
        backend["validated"] = True
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "base.json"
            proposed = root / "proposed.json"
            base.write_text(json.dumps({"models": [base_model]}), encoding="utf-8")
            proposed.write_text(json.dumps({"models": [proposed_model]}), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                result = verify_transitions(
                    argparse.Namespace(base_registry=base, registry=proposed)
                )
        self.assertEqual(result, 1)

    def test_transition_verifier_accepts_smoke_promotion(self) -> None:
        base_model = self.model()
        proposed_model = deepcopy(base_model)
        result = {
            "contract_sha256": contract_sha256(
                proposed_model, proposed_model["backends"]["audio_separator"]
            )
        }
        promote(proposed_model, result)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "base.json"
            proposed = root / "proposed.json"
            base.write_text(json.dumps({"models": [base_model]}), encoding="utf-8")
            proposed.write_text(json.dumps({"models": [proposed_model]}), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                status = verify_transitions(
                    argparse.Namespace(base_registry=base, registry=proposed)
                )
        self.assertEqual(status, 0)

    def test_transition_verifier_rejects_removing_smoke_evidence(self) -> None:
        base_model = self.model()
        promote(
            base_model,
            {
                "contract_sha256": contract_sha256(
                    base_model, base_model["backends"]["audio_separator"]
                )
            },
        )
        proposed_model = deepcopy(base_model)
        del proposed_model["backends"]["audio_separator"]["smoke_validation"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "base.json"
            proposed = root / "proposed.json"
            base.write_text(json.dumps({"models": [base_model]}), encoding="utf-8")
            proposed.write_text(json.dumps({"models": [proposed_model]}), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                status = verify_transitions(
                    argparse.Namespace(base_registry=base, registry=proposed)
                )
        self.assertEqual(status, 1)

    def test_registry_validator_accepts_automated_smoke_evidence(self) -> None:
        registry = json.loads((ROOT / "registry.json").read_text(encoding="utf-8"))
        self.assertTrue(
            any(
                "smoke_validation" in model["backends"]["audio_separator"]
                for model in registry["models"]
            )
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", encoding="utf-8") as handle:
            json.dump(registry, handle)
            handle.flush()
            completed = subprocess.run(
                ["python3", str(SCRIPTS / "validate.py"), handle.name],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_runner_output_allows_only_smoke_promotions(self) -> None:
        original_model = self.model()
        promoted_model = deepcopy(original_model)
        promote(
            promoted_model,
            {
                "contract_sha256": contract_sha256(
                    promoted_model, promoted_model["backends"]["audio_separator"]
                )
            },
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / "original.json"
            promoted = root / "promoted.json"
            original.write_text(json.dumps({"models": [original_model]}), encoding="utf-8")
            promoted.write_text(json.dumps({"models": [promoted_model]}), encoding="utf-8")
            arguments = argparse.Namespace(
                registry=original, promoted_registry=promoted
            )
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(verify_promotions(arguments), 0)
            promoted_model["name"] = "runner-controlled change"
            promoted.write_text(json.dumps({"models": [promoted_model]}), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(verify_promotions(arguments), 1)

    def test_runner_output_allows_stale_runtime_revalidation(self) -> None:
        original_model = self.model()
        promote(
            original_model,
            {
                "contract_sha256": contract_sha256(
                    original_model, original_model["backends"]["audio_separator"]
                )
            },
        )
        original_model["backends"]["audio_separator"]["smoke_validation"][
            "runtime_revision"
        ] = "0" * 40
        revalidated_model = deepcopy(original_model)
        promote(
            revalidated_model,
            {
                "contract_sha256": contract_sha256(
                    revalidated_model,
                    revalidated_model["backends"]["audio_separator"],
                )
            },
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / "original.json"
            promoted = root / "promoted.json"
            original.write_text(json.dumps({"models": [original_model]}), encoding="utf-8")
            promoted.write_text(
                json.dumps({"models": [revalidated_model]}), encoding="utf-8"
            )
            arguments = argparse.Namespace(registry=original, promoted_registry=promoted)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(verify_promotions(arguments), 0)

    def test_stale_smoke_runtime_is_automatically_revalidated(self) -> None:
        model = self.model()
        promote(
            model,
            {
                "contract_sha256": contract_sha256(
                    model, model["backends"]["audio_separator"]
                )
            },
        )
        model["backends"]["audio_separator"]["smoke_validation"][
            "runtime_revision"
        ] = "0" * 40
        registry = {"models": [model]}
        self.assertEqual(
            [item["id"] for item in pending_models(registry, registry, True)],
            ["test-model"],
        )

    def test_contract_digest_changes_with_exact_outputs(self) -> None:
        model = self.model()
        backend = model["backends"]["audio_separator"]
        before = contract_sha256(model, backend)
        backend["outputs"][0]["runtime_key"] = "Different"
        self.assertNotEqual(before, contract_sha256(model, backend))

    def test_structurally_valid_silent_specialist_output_is_allowed(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".wav") as handle:
            with wave.open(handle.name, "wb") as output:
                output.setnchannels(2)
                output.setsampwidth(2)
                output.setframerate(44100)
                output.writeframes(b"\0\0\0\0" * 44100)
            report = verify_wave(Path(handle.name), 44100)
        self.assertFalse(report["nonzero_audio"])

    def test_listening_evaluation_only_tracks_selection_changes(self) -> None:
        base = {"recommendations": {"vocals": {"model": "a", "alternatives": []}}}
        metadata_only = {
            "recommendations": {
                "vocals": {"model": "a", "alternatives": [{"model": "b"}]}
            }
        }
        replacement = {"recommendations": {"vocals": {"model": "b"}}}
        with patch.dict(os.environ, {"STEMS": ""}):
            self.assertEqual(changed_tasks(base, metadata_only), [])
            self.assertEqual(changed_tasks(base, replacement), ["vocals"])


if __name__ == "__main__":
    unittest.main()
