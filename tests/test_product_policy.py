from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from product_catalog import generate  # noqa: E402
from product_policy import group_for, label_for, multitrack_policy_errors  # noqa: E402


class ProductPolicyTests(unittest.TestCase):
    def test_unknown_capability_remains_browseable(self) -> None:
        self.assertEqual(group_for("accordion_like_future_stem"), "other")
        self.assertEqual(label_for("accordion_like_future_stem"), "Accordion Like Future Stem")

    def test_general_six_stem_decomposition_is_eligible(self) -> None:
        self.assertEqual(
            multitrack_policy_errors(
                {
                    "scope": "general_music",
                    "hierarchy": "top_level",
                    "outputs": ["vocals", "drums", "bass", "guitar", "piano", "other"],
                    "remainder": "other",
                    "reconstruction": {
                        "mode": "native",
                        "validated": True,
                        "validation_scope": "general_music_suite",
                        "suite": "general-music-reconstruction-v1",
                    },
                }
            ),
            [],
        )

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
        self.assertTrue(any("reconstruction" in error for error in errors))

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


if __name__ == "__main__":
    unittest.main()
