"""Authorization shared by privileged PR workflows, executed from main only."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


OWNER_ID = 73347504
REPOSITORY_ID = 1332928462


def authorize_pr(pr: dict, trusted_sha: str, expected_head: str | None = None) -> dict:
    """Fail closed on forks, other authors, closed PRs, or stale run inputs."""
    if (
        pr.get("state") != "open"
        or pr.get("draft") is not False
        or pr.get("user", {}).get("id") != OWNER_ID
        or pr.get("base", {}).get("repo", {}).get("id") != REPOSITORY_ID
        or (pr.get("head", {}).get("repo") or {}).get("id") != REPOSITORY_ID
        or pr.get("base", {}).get("ref") != "main"
        or pr.get("base", {}).get("sha") != trusted_sha
    ):
        raise ValueError("Only open, non-draft owner PRs from this repository to current main are authorized")
    head = pr["head"]["sha"]
    if not all(re.fullmatch(r"[0-9a-f]{40}", sha) for sha in (trusted_sha, head)):
        raise ValueError("Invalid commit SHA")
    if expected_head is not None and head != expected_head:
        raise ValueError("The PR changed while the workflow was running; rerun on the new head")
    number = pr["number"]
    if type(number) is not int or number < 1:
        raise ValueError("Invalid PR number")
    head_ref = pr["head"]["ref"]
    if not isinstance(head_ref, str) or not head_ref or any(c in head_ref for c in "\r\n"):
        raise ValueError("Invalid branch name")
    return {"number": number, "base_sha": trusted_sha, "head_sha": head, "head_ref": head_ref}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pr-json", type=Path, required=True)
    parser.add_argument("--trusted-sha", required=True)
    parser.add_argument("--expected-head")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = authorize_pr(json.loads(args.pr_json.read_text()), args.trusted_sha, args.expected_head)
    if args.output:
        with args.output.open("a") as output:
            for name, value in result.items():
                output.write(f"{name}={value}\n")


if __name__ == "__main__":
    main()
