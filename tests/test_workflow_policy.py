from __future__ import annotations

from copy import deepcopy
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from workflow_policy import OWNER_ID, REPOSITORY_ID, authorize_pr


class WorkflowPolicyTests(unittest.TestCase):
    def pr(self) -> dict:
        return {
            "number": 17,
            "state": "open",
            "draft": False,
            "user": {"id": OWNER_ID},
            "base": {"ref": "main", "sha": "a" * 40, "repo": {"id": REPOSITORY_ID}},
            "head": {"ref": "maintenance/models", "sha": "b" * 40, "repo": {"id": REPOSITORY_ID}},
        }

    def test_owner_pr_on_current_main_is_authorized(self):
        self.assertEqual(authorize_pr(self.pr(), "a" * 40)["head_sha"], "b" * 40)

    def test_rejects_forks_other_authors_and_untrusted_bases(self):
        for section, field, value in (
            ("head", "repo", {"id": 1, "full_name": "HAGerox/Stem-Separator-Models"}),
            ("base", "repo", {"id": 1}),
            ("user", "id", 1),
            ("base", "ref", "old-branch"),
            ("base", "sha", "c" * 40),
            ("head", "sha", "bad-sha"),
            ("head", "ref", "branch\nhead_sha=injected"),
        ):
            with self.subTest(section=section, field=field):
                pr = deepcopy(self.pr())
                pr[section][field] = value
                with self.assertRaises(ValueError):
                    authorize_pr(pr, "a" * 40)

    def test_rejects_closed_and_draft_prs(self):
        for field, value in (("state", "closed"), ("draft", True), ("number", "17\nfoo=bar")):
            with self.subTest(field=field):
                pr = self.pr()
                pr[field] = value
                with self.assertRaises(ValueError):
                    authorize_pr(pr, "a" * 40)

    def test_write_jobs_reject_a_new_head(self):
        with self.assertRaisesRegex(ValueError, "PR changed"):
            authorize_pr(self.pr(), "a" * 40, expected_head="c" * 40)
        authorize_pr(self.pr(), "a" * 40, expected_head="b" * 40)


if __name__ == "__main__":
    unittest.main()
