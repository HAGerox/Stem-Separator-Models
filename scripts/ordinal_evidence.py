"""Resolve source-attributed ordinal evidence into conservative rankings.

This module never turns prose into a comparison.  It consumes comparisons
already present in schema-4 registry data and derives measured comparisons
only from compatible rows in the same benchmark suite and stem.
"""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from typing import Any, Iterable

from evidence_policy import ORDINAL_CONFIDENCE_ORDER, SOURCE_TIER_ORDER


ComparisonKey = tuple[str, str, str, str, str]


def invert_relation(relation: str) -> str:
    if relation == "better":
        return "worse"
    if relation == "worse":
        return "better"
    return relation


def canonical_pair(left: str, right: str, relation: str) -> tuple[str, str, str]:
    """Return a stable endpoint order while preserving relation meaning."""

    if left <= right:
        return left, right, relation
    return right, left, invert_relation(relation)


def _qualitative_tier(registry: dict[str, Any], row: dict[str, Any]) -> str | None:
    source = row.get("source", {})
    snapshot = registry.get("source_snapshots", {}).get(source.get("snapshot"), {})
    tiers = snapshot.get("tiers", {}) if isinstance(snapshot, dict) else {}
    return tiers.get("qualitative") if isinstance(tiers, dict) else None


def resolve_ordinal_evidence(
    registry: dict[str, Any],
    *,
    task: str | None = None,
    context: str | None = None,
    minimum_confidence: str = "medium",
) -> dict[ComparisonKey, dict[str, Any]]:
    """Resolve direct evidence at the best available source tier.

    Repeated agreement at a tier preserves all provenance but does not receive
    extra votes.  Any same-tier disagreement remains an explicit conflict.
    """

    minimum = ORDINAL_CONFIDENCE_ORDER[minimum_confidence]
    grouped: dict[ComparisonKey, list[dict[str, Any]]] = defaultdict(list)
    for row in registry.get("ordinal_evidence", []):
        if not isinstance(row, dict):
            continue
        if task is not None and row.get("task") != task:
            continue
        if context is not None and row.get("context") != context:
            continue
        confidence = row.get("confidence")
        if ORDINAL_CONFIDENCE_ORDER.get(confidence, 0) < minimum:
            continue
        left = row.get("left", {}).get("model")
        right = row.get("right", {}).get("model")
        relation = row.get("relation")
        if not all(isinstance(item, str) for item in (left, right, relation)):
            continue
        left, right, relation = canonical_pair(left, right, relation)
        key = (row.get("task"), row.get("context"), row.get("metric"), left, right)
        tier = _qualitative_tier(registry, row)
        if tier not in SOURCE_TIER_ORDER:
            continue
        grouped[key].append({"row": row, "relation": relation, "tier": tier})

    resolved: dict[ComparisonKey, dict[str, Any]] = {}
    for key, observations in grouped.items():
        best_tier = min(observations, key=lambda item: SOURCE_TIER_ORDER[item["tier"]])["tier"]
        selected = [item for item in observations if item["tier"] == best_tier]
        relations = sorted({item["relation"] for item in selected})
        resolved[key] = {
            "relation": relations[0] if len(relations) == 1 else "conflict",
            "tier": best_tier,
            "evidence_ids": sorted(item["row"]["id"] for item in selected),
            "ignored_lower_tier_ids": sorted(
                item["row"]["id"] for item in observations if item["tier"] != best_tier
            ),
            "kind": "ordinal",
        }
    return resolved


def derive_measured_comparisons(
    registry: dict[str, Any], *, task: str | None = None
) -> dict[ComparisonKey, dict[str, Any]]:
    """Derive exact pair relations without changing measured benchmark rows."""

    metrics = registry.get("metric_definitions", {})
    by_context: dict[tuple[str, str], list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for model in registry.get("models", []):
        if not isinstance(model, dict):
            continue
        model_id = model.get("id")
        for result in model.get("benchmarks", []):
            if not isinstance(result, dict):
                continue
            stem = result.get("stem")
            if task is not None and stem != task:
                continue
            suite = result.get("suite")
            if isinstance(model_id, str) and isinstance(suite, str) and isinstance(stem, str):
                by_context[(suite, stem)].append((model_id, result))

    output: dict[ComparisonKey, dict[str, Any]] = {}
    for (suite, stem), rows in by_context.items():
        context_id = f"benchmark:{suite}:{stem}"
        for (left_id, left_row), (right_id, right_row) in combinations(
            sorted(rows, key=lambda item: item[0]), 2
        ):
            left_values = left_row.get("values", {})
            right_values = right_row.get("values", {})
            for metric_id in sorted(set(left_values) & set(right_values)):
                definition = metrics.get(metric_id, {})
                if definition.get("kind") != "measured":
                    continue
                left_value = left_values[metric_id]
                right_value = right_values[metric_id]
                if left_value == right_value:
                    relation = "tie"
                else:
                    left_is_better = (
                        left_value > right_value
                        if definition.get("better") == "higher"
                        else left_value < right_value
                    )
                    relation = "better" if left_is_better else "worse"
                key = (stem, context_id, metric_id, left_id, right_id)
                output[key] = {
                    "relation": relation,
                    "kind": "measured",
                    "suite": suite,
                    "evidence_ids": [
                        f"{left_id}:{suite}:{stem}",
                        f"{right_id}:{suite}:{stem}",
                    ],
                    "values": {left_id: left_value, right_id: right_value},
                }
    return output


def eligible_candidates(registry: dict[str, Any], task: str) -> list[str]:
    """Return quality-neutral recommendation candidates for a task."""

    candidates = [
        model
        for model in registry.get("models", [])
        if isinstance(model, dict)
        and task in model.get("tasks", [])
        and model.get("status") not in {"deprecated"}
        and model.get("availability", {}).get("state") == "public_weights"
        and any(
            isinstance(details, dict)
            and details.get("state")
            in {"validated", "listed", "declared", "custom_code", "compatible_unvalidated"}
            for details in model.get("backends", {}).values()
        )
    ]
    stable = [model for model in candidates if model.get("status") != "experimental"]
    return sorted(model["id"] for model in (stable or candidates))


def _pair_outcomes(
    left: str,
    right: str,
    comparisons: dict[ComparisonKey, dict[str, Any]],
    metric_weights: dict[str, float],
    context_ids: set[str],
) -> dict[str, Any]:
    first, second, _ = canonical_pair(left, right, "tie")
    by_metric: dict[str, set[str]] = defaultdict(set)
    traces: dict[str, list[str]] = defaultdict(list)
    for (unused_task, context, metric, pair_left, pair_right), result in comparisons.items():
        del unused_task
        if context not in context_ids or metric not in metric_weights:
            continue
        if (pair_left, pair_right) != (first, second):
            continue
        relation = result.get("relation")
        if first != left:
            relation = invert_relation(relation)
        by_metric[metric].add(relation)
        traces[metric].extend(result.get("evidence_ids", []))

    better: list[str] = []
    worse: list[str] = []
    tied: list[str] = []
    unresolved: list[str] = []
    covered_weight = 0.0
    for metric, relations in sorted(by_metric.items()):
        if len(relations) != 1 or "conflict" in relations or "incomparable" in relations:
            unresolved.append(metric)
            continue
        relation = next(iter(relations))
        covered_weight += metric_weights[metric]
        if relation == "better":
            better.append(metric)
        elif relation == "worse":
            worse.append(metric)
        elif relation == "tie":
            tied.append(metric)
    policy_weight = sum(metric_weights.values())
    observed_weight = sum(metric_weights[metric] for metric in by_metric)
    coverage = covered_weight / observed_weight if observed_weight else 0.0
    policy_coverage = covered_weight / policy_weight if policy_weight else 0.0
    return {
        "better": better,
        "worse": worse,
        "tied": tied,
        "unresolved": unresolved,
        "coverage": coverage,
        "policy_coverage": policy_coverage,
        "traces": {metric: sorted(set(ids)) for metric, ids in traces.items()},
    }


def _strongly_connected_components(
    nodes: Iterable[str], edges: dict[str, set[str]]
) -> list[list[str]]:
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    components: list[list[str]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for target in sorted(edges.get(node, set())):
            if target not in indices:
                visit(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[target])
        if lowlinks[node] == indices[node]:
            component = []
            while True:
                target = stack.pop()
                on_stack.remove(target)
                component.append(target)
                if target == node:
                    break
            components.append(sorted(component))

    for node in sorted(nodes):
        if node not in indices:
            visit(node)
    return components


def dominance_ranking(
    candidates: Iterable[str],
    comparisons: dict[ComparisonKey, dict[str, Any]],
    *,
    metric_weights: dict[str, float],
    context_ids: Iterable[str],
    minimum_coverage: float,
) -> dict[str, Any]:
    """Return deterministic nondominated fronts and auditable pair decisions."""

    candidates = sorted(set(candidates))
    contexts = set(context_ids)
    edges: dict[str, set[str]] = {candidate: set() for candidate in candidates}
    decisions: dict[str, dict[str, Any]] = {}
    for left, right in combinations(candidates, 2):
        outcome = _pair_outcomes(left, right, comparisons, metric_weights, contexts)
        winner = None
        loser = None
        if outcome["coverage"] >= minimum_coverage:
            if outcome["better"] and not outcome["worse"]:
                winner, loser = left, right
            elif outcome["worse"] and not outcome["better"]:
                winner, loser = right, left
        if winner is not None and loser is not None:
            edges[winner].add(loser)
        decisions[f"{left}|{right}"] = {
            **outcome,
            "winner": winner,
        }

    components = _strongly_connected_components(candidates, edges)
    component_for = {
        member: component_index
        for component_index, component in enumerate(components)
        for member in component
    }
    component_edges: dict[int, set[int]] = {index: set() for index in range(len(components))}
    indegrees = {index: 0 for index in range(len(components))}
    for source, targets in edges.items():
        source_component = component_for[source]
        for target in targets:
            target_component = component_for[target]
            if source_component == target_component or target_component in component_edges[source_component]:
                continue
            component_edges[source_component].add(target_component)
            indegrees[target_component] += 1

    fronts: list[list[str]] = []
    remaining = set(range(len(components)))
    while remaining:
        current = sorted(
            (index for index in remaining if indegrees[index] == 0),
            key=lambda index: components[index],
        )
        if not current:
            current = [min(remaining, key=lambda index: components[index])]
        fronts.append(sorted(member for index in current for member in components[index]))
        for index in current:
            remaining.remove(index)
            for target in component_edges[index]:
                indegrees[target] -= 1

    return {
        "fronts": fronts,
        "conflict_groups": sorted(
            (component for component in components if len(component) > 1),
            key=lambda component: component,
        ),
        "decisions": decisions,
    }


def derive_task_ranking(
    registry: dict[str, Any],
    task: str,
    *,
    context_ids: Iterable[str],
    metric_weights: dict[str, float],
    minimum_coverage: float = 0.25,
    minimum_confidence: str = "medium",
    candidates: Iterable[str] | None = None,
) -> dict[str, Any]:
    comparisons = resolve_ordinal_evidence(
        registry, task=task, minimum_confidence=minimum_confidence
    )
    comparisons.update(derive_measured_comparisons(registry, task=task))
    return dominance_ranking(
        candidates if candidates is not None else eligible_candidates(registry, task),
        comparisons,
        metric_weights=metric_weights,
        context_ids=context_ids,
        minimum_coverage=minimum_coverage,
    )


def recommendation_action(ranking: dict[str, Any], incumbent: str | None) -> dict[str, Any]:
    """Turn a partial ranking into a conservative recommendation action."""

    fronts = ranking.get("fronts", [])
    if not fronts or not fronts[0]:
        return {"action": "review_required", "reason": "no_eligible_candidate"}
    first_front = fronts[0]
    if len(first_front) == 1:
        winner = first_front[0]
        if winner == incumbent:
            return {"action": "keep", "model": winner, "reason": "unique_first_front"}
        return {
            "action": "replace" if incumbent is not None else "select",
            "model": winner,
            "previous_model": incumbent,
            "reason": "only_eligible" if len(ranking.get("decisions", {})) == 0 else "unique_first_front",
        }
    if incumbent in first_front:
        return {
            "action": "keep",
            "model": incumbent,
            "reason": "incumbent_remains_nondominated",
            "first_front": first_front,
        }
    return {
        "action": "review_required",
        "reason": "multiple_nondominated_candidates",
        "first_front": first_front,
    }
