#!/usr/bin/env python3
"""Render deterministic schema-4 ordinal ranking fronts for one task."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from evidence_policy import ORDINAL_RECOMMENDATION_POLICIES
from ordinal_evidence import (
    derive_measured_comparisons,
    dominance_ranking,
    eligible_candidates,
    resolve_ordinal_evidence,
)


ROOT = Path(__file__).resolve().parents[1]


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def ranking_report(
    registry: dict[str, Any], task: str, policy_id: str, requested_contexts: list[str]
) -> dict[str, Any]:
    policy = ORDINAL_RECOMMENDATION_POLICIES[policy_id]
    task_weights = policy["task_weights"]
    weights = task_weights.get(task, task_weights[policy["default_task_weights"]])
    comparisons = resolve_ordinal_evidence(
        registry,
        task=task,
        minimum_confidence=policy["minimum_confidence"],
    )
    comparisons.update(derive_measured_comparisons(registry, task=task))
    known_contexts = sorted(
        {key[1] for key in comparisons}
    )
    contexts = requested_contexts or known_contexts
    unknown = sorted(set(contexts) - set(known_contexts))
    if unknown:
        raise ValueError("Contexts have no usable evidence: " + ", ".join(unknown))
    candidates = eligible_candidates(registry, task)
    incumbent = registry.get("recommendations", {}).get(task, {}).get("model")
    reports = {}
    for context in contexts:
        observed_candidates = sorted(
            {
                model_id
                for key in comparisons
                if key[1] == context
                for model_id in key[3:5]
                if model_id in candidates
            }
        )
        ranking = dominance_ranking(
            observed_candidates,
            comparisons,
            metric_weights=weights,
            context_ids=[context],
            minimum_coverage=policy["minimum_coverage"],
        )
        reports[context] = {
            **ranking,
            "uncompared_candidates": sorted(set(candidates) - set(observed_candidates)),
        }
    return {
        "schema": 1,
        "registry_schema": registry.get("schema"),
        "task": task,
        "policy": policy_id,
        "incumbent": incumbent,
        "candidates": candidates,
        "contexts": reports,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task")
    parser.add_argument("--registry", type=Path, default=ROOT / "registry.json")
    parser.add_argument("--policy", default="ordinal-quality-v1")
    parser.add_argument("--context", action="append", default=[])
    args = parser.parse_args()
    registry = load(args.registry)
    if registry.get("schema") != 4:
        raise RuntimeError("Ordinal ranking requires a schema-4 registry")
    if args.policy not in ORDINAL_RECOMMENDATION_POLICIES:
        raise RuntimeError(f"Unknown ordinal policy: {args.policy}")
    print(json.dumps(ranking_report(registry, args.task, args.policy, args.context), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
