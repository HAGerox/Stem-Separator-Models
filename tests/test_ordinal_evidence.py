from __future__ import annotations

import sys
import unittest
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ordinal_evidence import (  # noqa: E402
    canonical_pair,
    derive_measured_comparisons,
    dominance_ranking,
    recommendation_action,
    resolve_ordinal_evidence,
)


class OrdinalEvidenceTests(unittest.TestCase):
    def observation(
        self, evidence_id: str, relation: str, snapshot: str, confidence: str = "high"
    ) -> dict:
        return {
            "id": evidence_id,
            "task": "vocals",
            "metric": "bleed_control",
            "context": "general-v1",
            "left": {"model": "model-a"},
            "right": {"model": "model-b"},
            "relation": relation,
            "confidence": confidence,
            "source": {"snapshot": snapshot},
        }

    def test_canonical_pair_inverts_direction(self) -> None:
        self.assertEqual(
            canonical_pair("model-b", "model-a", "better"),
            ("model-a", "model-b", "worse"),
        )
        self.assertEqual(
            canonical_pair("model-b", "model-a", "incomparable"),
            ("model-a", "model-b", "incomparable"),
        )

    def test_best_source_tier_wins_without_extra_votes(self) -> None:
        registry = {
            "source_snapshots": {
                "primary": {"tiers": {"qualitative": "tier_1"}},
                "secondary": {"tiers": {"qualitative": "tier_2"}},
            },
            "ordinal_evidence": [
                self.observation("primary-observation", "better", "primary"),
                self.observation("secondary-observation", "worse", "secondary"),
            ],
        }
        result = next(iter(resolve_ordinal_evidence(registry).values()))
        self.assertEqual(result["relation"], "better")
        self.assertEqual(result["evidence_ids"], ["primary-observation"])
        self.assertEqual(result["ignored_lower_tier_ids"], ["secondary-observation"])

    def test_same_tier_disagreement_is_a_conflict(self) -> None:
        registry = {
            "source_snapshots": {
                "primary": {"tiers": {"qualitative": "tier_1"}},
            },
            "ordinal_evidence": [
                self.observation("first", "better", "primary"),
                self.observation("second", "worse", "primary"),
            ],
        }
        result = next(iter(resolve_ordinal_evidence(registry).values()))
        self.assertEqual(result["relation"], "conflict")

    def test_explicit_tie_remains_a_shared_front(self) -> None:
        comparisons = {
            ("vocals", "general-v1", "quality", "a", "b"): {
                "relation": "tie",
                "evidence_ids": ["explicit-tie"],
            },
        }
        ranking = dominance_ranking(
            ["a", "b"],
            comparisons,
            metric_weights={"quality": 1.0},
            context_ids=["general-v1"],
            minimum_coverage=1.0,
        )
        self.assertEqual(ranking["fronts"], [["a", "b"]])
        self.assertEqual(ranking["decisions"]["a|b"]["tied"], ["quality"])

    def test_low_confidence_is_retained_but_not_ranked_by_default(self) -> None:
        registry = {
            "source_snapshots": {
                "primary": {"tiers": {"qualitative": "tier_1"}},
            },
            "ordinal_evidence": [
                self.observation("unclear", "better", "primary", confidence="low"),
            ],
        }
        self.assertEqual(resolve_ordinal_evidence(registry), {})

    def test_measured_comparisons_stay_within_suite_and_stem(self) -> None:
        registry = {
            "metric_definitions": {
                "sdr_db": {"kind": "measured", "better": "higher"},
            },
            "models": [
                {
                    "id": "model-a",
                    "benchmarks": [
                        {"suite": "suite-1", "stem": "vocals", "values": {"sdr_db": 10.5}}
                    ],
                },
                {
                    "id": "model-b",
                    "benchmarks": [
                        {"suite": "suite-1", "stem": "vocals", "values": {"sdr_db": 10.0}}
                    ],
                },
                {
                    "id": "model-c",
                    "benchmarks": [
                        {"suite": "suite-2", "stem": "vocals", "values": {"sdr_db": 99.0}}
                    ],
                },
            ],
        }
        before = deepcopy(registry)
        comparisons = derive_measured_comparisons(registry, task="vocals")
        self.assertEqual(len(comparisons), 1)
        key, result = next(iter(comparisons.items()))
        self.assertEqual(key, ("vocals", "benchmark:suite-1:vocals", "sdr_db", "model-a", "model-b"))
        self.assertEqual(result["relation"], "better")
        self.assertEqual(result["values"], {"model-a": 10.5, "model-b": 10.0})
        self.assertEqual(registry, before)

    def test_tradeoff_remains_one_nondominated_front(self) -> None:
        comparisons = {
            ("vocals", "general-v1", "bleed", "a", "b"): {
                "relation": "better",
                "evidence_ids": ["bleed"],
            },
            ("vocals", "general-v1", "fullness", "a", "b"): {
                "relation": "worse",
                "evidence_ids": ["fullness"],
            },
        }
        ranking = dominance_ranking(
            ["a", "b"],
            comparisons,
            metric_weights={"bleed": 0.5, "fullness": 0.5},
            context_ids=["general-v1"],
            minimum_coverage=0.5,
        )
        self.assertEqual(ranking["fronts"], [["a", "b"]])
        self.assertIsNone(ranking["decisions"]["a|b"]["winner"])

    def test_direct_edge_orders_pair_without_inventing_missing_metrics(self) -> None:
        comparisons = {
            ("vocals", "specific-v1", "bleed", "a", "b"): {
                "relation": "better",
                "evidence_ids": ["direct-source-edge"],
            },
        }
        ranking = dominance_ranking(
            ["a", "b"],
            comparisons,
            metric_weights={"bleed": 0.2, "fullness": 0.8},
            context_ids=["specific-v1"],
            minimum_coverage=1.0,
        )
        self.assertEqual(ranking["fronts"], [["a"], ["b"]])
        decision = ranking["decisions"]["a|b"]
        self.assertEqual(decision["coverage"], 1.0)
        self.assertEqual(decision["policy_coverage"], 0.2)

    def test_dominance_cycle_is_exposed_as_conflict_group(self) -> None:
        comparisons = {
            ("vocals", "general-v1", "quality", "a", "b"): {
                "relation": "better",
                "evidence_ids": ["a-b"],
            },
            ("vocals", "general-v1", "quality", "b", "c"): {
                "relation": "better",
                "evidence_ids": ["b-c"],
            },
            ("vocals", "general-v1", "quality", "a", "c"): {
                "relation": "worse",
                "evidence_ids": ["c-a"],
            },
        }
        ranking = dominance_ranking(
            ["a", "b", "c"],
            comparisons,
            metric_weights={"quality": 1.0},
            context_ids=["general-v1"],
            minimum_coverage=1.0,
        )
        self.assertEqual(ranking["fronts"], [["a", "b", "c"]])
        self.assertEqual(ranking["conflict_groups"], [["a", "b", "c"]])

    def test_missing_evidence_does_not_reduce_quality(self) -> None:
        ranking = dominance_ranking(
            ["a", "b"],
            {},
            metric_weights={"quality": 1.0},
            context_ids=["general-v1"],
            minimum_coverage=0.25,
        )
        self.assertEqual(ranking["fronts"], [["a", "b"]])
        self.assertEqual(ranking["decisions"]["a|b"]["coverage"], 0.0)

    def test_incumbent_is_kept_when_first_front_is_incomparable(self) -> None:
        action = recommendation_action(
            {"fronts": [["a", "b"]], "decisions": {"a|b": {"winner": None}}},
            "b",
        )
        self.assertEqual(action["action"], "keep")
        self.assertEqual(action["reason"], "incumbent_remains_nondominated")

    def test_unique_first_front_can_replace_incumbent(self) -> None:
        action = recommendation_action(
            {"fronts": [["a"], ["b"]], "decisions": {"a|b": {"winner": "a"}}},
            "b",
        )
        self.assertEqual(action["action"], "replace")
        self.assertEqual(action["model"], "a")


if __name__ == "__main__":
    unittest.main()
