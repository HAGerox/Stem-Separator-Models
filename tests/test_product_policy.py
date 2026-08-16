from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from product_catalog import generate, normalized_outputs  # noqa: E402
from product_policy import (  # noqa: E402
    group_for,
    label_for,
    multitrack_policy_errors,
    multitrack_reconstruction_errors,
)


class ProductPolicyTests(unittest.TestCase):
    @staticmethod
    def multitrack_registry(*, tasks: list[str] | None = None) -> dict:
        stems = ["vocals", "drums", "bass", "guitar", "piano", "other"]
        artifact = {
            "name": "model.ckpt",
            "url": "https://example.test/model.ckpt",
            "sha256": "a" * 64,
        }
        return {
            "schema": 3,
            "generated_at": "2026-08-16",
            "source_snapshots": {},
            "models": [
                {
                    "id": "six-stem",
                    "name": "Six stem",
                    "architecture": "test",
                    "status": "current",
                    "tasks": tasks if tasks is not None else [*stems, "multitrack"],
                    "availability": {"state": "public_weights", "artifacts": [artifact]},
                    "backends": {
                        "audio_separator": {
                            "state": "validated",
                            "validated": True,
                            "model_filename": "model.ckpt",
                            "outputs": [
                                {"runtime_key": stem, "capability": stem}
                                for stem in stems
                            ],
                            "artifact_names": ["model.ckpt"],
                        }
                    },
                    "decompositions": {
                        "general_music_6": {
                            "scope": "general_music",
                            "hierarchy": "top_level",
                            "outputs": stems,
                            "remainder": "other",
                            "reconstruction": {
                                "mode": "residual_to_remainder",
                                "validated": True,
                                "validation_scope": "exact_checkpoint_smoke",
                                "suite": "synthetic-smoke-v1",
                            },
                        }
                    },
                }
            ],
            "recommendations": {
                "multitrack": {
                    "model": "six-stem",
                    "decomposition": "general_music_6",
                    "policy": "quality",
                    "alternatives": [],
                }
            },
        }

    def test_unknown_capability_remains_browseable(self) -> None:
        self.assertEqual(group_for("accordion_like_future_stem"), "other")
        self.assertEqual(label_for("accordion_like_future_stem"), "Accordion Like Future Stem")

    def test_general_six_stem_decomposition_is_eligible_without_reconstruction(self) -> None:
        self.assertEqual(
            multitrack_policy_errors(
                {
                    "scope": "general_music",
                    "hierarchy": "top_level",
                    "outputs": ["vocals", "drums", "bass", "guitar", "piano", "other"],
                    "remainder": "other",
                }
            ),
            [],
        )

    def test_specialist_outputs_do_not_qualify_as_broad_multitrack(self) -> None:
        errors = multitrack_policy_errors(
            {
                "scope": "general_music",
                "hierarchy": "top_level",
                "outputs": ["vocals", "drums", "bass", "violin", "other"],
                "remainder": "other",
            }
        )
        self.assertTrue(any("non-broad" in error and "violin" in error for error in errors))

    def test_exact_checkpoint_smoke_is_not_general_reconstruction_validation(self) -> None:
        errors = multitrack_reconstruction_errors(
            {
                "mode": "residual_to_remainder",
                "validated": True,
                "validation_scope": "exact_checkpoint_smoke",
                "suite": "synthetic-smoke-v1",
                "residual_rms_ratio": 0.038,
            }
        )
        self.assertIn("validation_scope must be general_music_suite", errors)

    def test_general_music_reconstruction_suite_is_valid_separately(self) -> None:
        self.assertEqual(
            multitrack_reconstruction_errors(
                {
                    "mode": "native",
                    "validated": True,
                    "validation_scope": "general_music_suite",
                    "suite": "general-music-reconstruction-v1",
                    "residual_rms_ratio": 0.02,
                    "residual_db": -33.98,
                }
            ),
            [],
        )

    def test_catalogue_does_not_advertise_unimplemented_residual_correction(self) -> None:
        multitrack = generate(self.multitrack_registry())["multitrack"]

        self.assertTrue(multitrack["available"])
        self.assertNotIn("reconstruction", multitrack["decomposition"])
        self.assertFalse(multitrack["reconstruction"]["available"])
        self.assertIn(
            "validation_scope must be general_music_suite",
            multitrack["reconstruction"]["errors"],
        )
        self.assertTrue(
            any("not implemented" in error for error in multitrack["reconstruction"]["errors"])
        )

    def test_catalogue_can_advertise_separately_validated_native_reconstruction(self) -> None:
        registry = self.multitrack_registry()
        reconstruction = registry["models"][0]["decompositions"]["general_music_6"][
            "reconstruction"
        ]
        reconstruction.update(
            {
                "mode": "native",
                "validation_scope": "general_music_suite",
                "suite": "general-music-reconstruction-v1",
            }
        )

        multitrack = generate(registry)["multitrack"]

        self.assertTrue(multitrack["available"])
        self.assertTrue(multitrack["reconstruction"]["available"])
        self.assertEqual(multitrack["reconstruction"]["errors"], [])

    def test_model_must_explicitly_intend_its_multitrack_decomposition(self) -> None:
        multitrack = generate(
            self.multitrack_registry(
                tasks=["vocals", "drums", "bass", "guitar", "piano", "other"]
            )
        )["multitrack"]

        self.assertFalse(multitrack["available"])

    def test_independent_mega_extractor_is_not_multitrack(self) -> None:
        errors = multitrack_policy_errors(
            {
                "scope": "independent_sources",
                "hierarchy": "mixed",
                "outputs": [
                    "vocals",
                    "drums",
                    "kick",
                    "snare",
                    "bass",
                    "guitar",
                    "piano",
                    "other",
                    "violin",
                    "cello",
                    "trumpet",
                    "flute",
                    "organ",
                ],
                "remainder": "other",
                "reconstruction": {
                    "mode": "independent_non_additive",
                    "validated": False,
                },
            }
        )
        self.assertTrue(any("scope" in error for error in errors))
        self.assertTrue(any("4-12" in error for error in errors))
        self.assertTrue(any("mix drums" in error for error in errors))
        self.assertTrue(any("non-broad" in error for error in errors))

    def test_exact_runtime_alias_is_preserved(self) -> None:
        registry = {
            "schema": 3,
            "generated_at": "2026-08-16",
            "source_snapshots": {},
            "models": [
                {
                    "id": "drums",
                    "name": "Drums",
                    "architecture": "mdxc",
                    "status": "current",
                    "availability": {
                        "artifacts": [
                            {"name": "drums.ckpt", "url": "https://example/drums", "sha256": "a" * 64}
                        ]
                    },
                    "backends": {
                        "audio_separator": {
                            "state": "validated",
                            "validated": True,
                            "model_filename": "drums.ckpt",
                            "outputs": [{"runtime_key": "hh", "capability": "hihat"}],
                        }
                    },
                }
            ],
            "recommendations": {
                "hihat": {"model": "drums", "policy": "quality", "alternatives": []}
            },
        }
        catalogue = generate(registry)
        capability = catalogue["capabilities"][0]
        self.assertTrue(capability["available"])
        self.assertEqual(capability["backends"][0]["outputs"][0]["runtime_key"], "hh")
        self.assertEqual(capability["backends"][0]["outputs"][0]["capability"], "hihat")

    def test_legacy_string_output_contract_is_rejected(self) -> None:
        registry = {
            "schema": 3,
            "generated_at": "2026-08-16",
            "source_snapshots": {},
            "models": [
                {
                    "id": "legacy",
                    "name": "Legacy",
                    "architecture": "mdxc",
                    "status": "current",
                    "tasks": ["hihat"],
                    "availability": {"state": "public_weights", "artifacts": []},
                    "backends": {
                        "audio_separator": {
                            "state": "validated",
                            "validated": True,
                            "model_filename": "legacy.ckpt",
                            "outputs": ["hihat"],
                        }
                    },
                }
            ],
            "recommendations": {
                "hihat": {"model": "legacy", "policy": "quality", "alternatives": []}
            },
        }

        self.assertEqual(normalized_outputs({"outputs": ["hihat"]}), [])
        self.assertFalse(generate(registry)["capabilities"][0]["available"])


if __name__ == "__main__":
    unittest.main()
