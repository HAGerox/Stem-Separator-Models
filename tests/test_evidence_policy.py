from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from evidence_policy import RECOMMENDATION_POLICIES  # noqa: E402


class EvidencePolicyTests(unittest.TestCase):
    def test_registry_references_code_owned_policies(self) -> None:
        registry = json.loads((ROOT / "registry.json").read_text(encoding="utf-8"))
        self.assertNotIn("recommendation_policies", registry)
        self.assertNotIn("rules", registry["evidence_policy"])
        self.assertNotIn("semantic_scale", registry["evidence_policy"])
        for recommendation in registry["recommendations"].values():
            self.assertIn(recommendation["policy"], RECOMMENDATION_POLICIES)

    def test_policy_weights_are_normalized(self) -> None:
        for policy in RECOMMENDATION_POLICIES.values():
            self.assertAlmostEqual(
                policy["measured_weight"] + policy["semantic_weight"], 1.0
            )
            for weights in policy["task_weights"].values():
                self.assertAlmostEqual(sum(weights.values()), 1.0, places=7)


if __name__ == "__main__":
    unittest.main()
