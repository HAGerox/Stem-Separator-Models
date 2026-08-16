"""Versioned evidence extraction and recommendation policy.

This module is deliberately code-owned.  ``registry.json`` contains observations
and recommendation results, not procedural rules or tunable ranking weights.
"""

from __future__ import annotations


SEMANTIC_MIN = 0
SEMANTIC_MAX = 100

SEMANTIC_SCALE = {
    "severe_negative": 20,
    "negative": 35,
    "mixed_negative": 45,
    "neutral": 50,
    "mixed_positive": 60,
    "positive": 75,
    "strong_positive": 90,
    "exceptional": 95,
}

EXTRACTION_RULES = (
    "Only include models with public weights and a credible local inference path.",
    "Never select provider-only models or hosted ensembles as recommendation targets.",
    "Keep qualitative observations source-attributed and measured evidence separate.",
    "Copy source measurements exactly; never infer or zero-fill missing metrics.",
    "Compare measurements only within the same benchmark suite and protocol.",
    "Treat missing evidence as reduced coverage, not reduced quality.",
)

RECOMMENDATION_POLICIES = {
    "balanced-quality-v1": {
        "measured_weight": 0.5,
        "semantic_weight": 0.5,
        "missing": "reduce_coverage",
        "default_task_weights": "specialist",
        "task_weights": {
            "vocals": {
                "sdr_db": 0.14285714,
                "si_sdr_db": 0.06349206,
                "mvsep_bleedless": 0.13492064,
                "mvsep_fullness": 0.0952381,
                "l1_freq": 0.06349206,
                "bleed_control": 0.16216216,
                "fullness_preservation": 0.13513514,
                "artifact_control": 0.10810811,
                "robustness": 0.05405405,
                "tonal_fidelity": 0.04054054,
            },
            "instrumental": {
                "sdr_db": 0.13157895,
                "si_sdr_db": 0.05263158,
                "mvsep_bleedless": 0.12280702,
                "mvsep_fullness": 0.12280702,
                "l1_freq": 0.07017543,
                "bleed_control": 0.13953488,
                "fullness_preservation": 0.15116279,
                "artifact_control": 0.09302326,
                "robustness": 0.05813953,
                "tonal_fidelity": 0.05813954,
            },
            "specialist": {
                "sdr_db": 0.16363636,
                "si_sdr_db": 0.06363636,
                "mvsep_bleedless": 0.10909091,
                "mvsep_fullness": 0.09090909,
                "l1_freq": 0.07272728,
                "target_isolation": 0.16666667,
                "artifact_control": 0.11111111,
                "robustness": 0.08888889,
                "tonal_fidelity": 0.07777778,
                "fullness_preservation": 0.05555555,
            },
        },
    }
}
