from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from evidence_policy import (  # noqa: E402
    ORDINAL_CONFIDENCE_ORDER,
    ORDINAL_RECOMMENDATION_POLICIES,
    SOURCE_TIER_ORDER,
)


class EvidencePolicyTests(unittest.TestCase):
    def test_registry_references_code_owned_policies(self) -> None:
        registry = json.loads((ROOT / "registry.json").read_text(encoding="utf-8"))
        self.assertNotIn("recommendation_policies", registry)
        self.assertNotIn("rules", registry["evidence_policy"])
        self.assertNotIn("semantic_scale", registry["evidence_policy"])
        self.assertNotIn("primary_sources", registry["evidence_policy"])
        for recommendation in registry["recommendations"].values():
            self.assertIn(recommendation["policy"], ORDINAL_RECOMMENDATION_POLICIES)

    def test_policy_weights_are_normalized(self) -> None:
        for policy in ORDINAL_RECOMMENDATION_POLICIES.values():
            for weights in policy["task_weights"].values():
                self.assertAlmostEqual(sum(weights.values()), 1.0, places=7)

    def test_ordinal_policy_uses_weights_only_for_coverage(self) -> None:
        policy = ORDINAL_RECOMMENDATION_POLICIES["ordinal-quality-v1"]
        self.assertEqual(policy["missing"], "reduce_coverage")
        self.assertIn(policy["minimum_confidence"], ORDINAL_CONFIDENCE_ORDER)
        self.assertGreaterEqual(policy["minimum_coverage"], 0)
        self.assertLessEqual(policy["minimum_coverage"], 1)
        for weights in policy["task_weights"].values():
            self.assertAlmostEqual(sum(weights.values()), 1.0, places=7)

    def test_source_tiers_have_explicit_precedence(self) -> None:
        self.assertEqual(SOURCE_TIER_ORDER, {"tier_1": 1, "tier_2": 2, "tier_3": 3})


if __name__ == "__main__":
    unittest.main()
