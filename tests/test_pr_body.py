from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from pr_body import rows_changed_by_id, selection_signature, source_location  # noqa: E402


class PullRequestBodyTests(unittest.TestCase):
    def test_ordinal_update_is_not_reported_as_remove_and_add(self) -> None:
        changes = rows_changed_by_id(
            [{"id": "comparison-1", "relation": "better"}],
            [{"id": "comparison-1", "relation": "tie"}],
        )
        self.assertEqual(changes, [("Updated", {"id": "comparison-1", "relation": "tie"})])

    def test_selection_signature_ignores_policy_metadata(self) -> None:
        self.assertEqual(
            selection_signature({"model": "a", "policy": "old"}),
            selection_signature({"model": "a", "policy": "new", "basis": "recomputed"}),
        )

    def test_typed_source_locations_are_rendered(self) -> None:
        self.assertEqual(
            source_location({"location": {"kind": "line_range", "start": 10, "end": 12}}),
            "lines 10–12",
        )
        self.assertEqual(
            source_location({"location": {"kind": "json_pointer", "value": "/models/3"}}),
            "/models/3",
        )


if __name__ == "__main__":
    unittest.main()
