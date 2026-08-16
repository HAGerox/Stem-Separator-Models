#!/usr/bin/env python3
"""Generate the small, app-facing catalogue from the evidence registry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from product_policy import (
    EXCLUDED_CAPABILITIES,
    GROUP_ORDER,
    POLICY_VERSION,
    PRODUCT_BACKENDS,
    PROMOTED_CAPABILITIES,
    group_for,
    kind_for,
    label_for,
    multitrack_policy_errors,
)


ROOT = Path(__file__).resolve().parents[1]


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def normalized_outputs(details: dict[str, Any]) -> list[dict[str, str]]:
    """Normalize the temporary string form while emitting only canonical objects."""

    output: list[dict[str, str]] = []
    for item in details.get("outputs", []):
        if isinstance(item, str):
            output.append({"runtime_key": item, "capability": item})
        elif isinstance(item, dict):
            normalized = {
                "runtime_key": item["runtime_key"],
                "capability": item["capability"],
            }
            if isinstance(item.get("label"), str) and item["label"]:
                normalized["label"] = item["label"]
            output.append(normalized)
    return output


def backend_artifacts(model: dict[str, Any], details: dict[str, Any]) -> list[dict[str, Any]]:
    artifacts = model.get("availability", {}).get("artifacts", [])
    if not isinstance(artifacts, list):
        return []
    requested = details.get("artifact_names")
    if isinstance(requested, list):
        selected = [item for item in artifacts if item.get("name") in requested]
    else:
        selected = artifacts
    return [
        {key: item[key] for key in ("name", "url", "sha256") if key in item}
        for item in selected
        if isinstance(item, dict)
    ]


def immutable_install_source(
    registry: dict[str, Any], model: dict[str, Any], details: dict[str, Any]
) -> bool:
    artifacts = backend_artifacts(model, details)
    if artifacts and all(item.get("url") and item.get("sha256") for item in artifacts):
        return True
    snapshot_id = details.get("catalog_snapshot")
    snapshot = registry.get("source_snapshots", {}).get(snapshot_id, {})
    return isinstance(snapshot, dict) and bool(snapshot.get("sha256"))


def backend_contracts(
    registry: dict[str, Any], model: dict[str, Any], capability: str
) -> list[dict[str, Any]]:
    contracts = []
    for backend_id, details in sorted(model.get("backends", {}).items()):
        if backend_id not in PRODUCT_BACKENDS:
            continue
        if not isinstance(details, dict):
            continue
        outputs = normalized_outputs(details)
        matching = [item for item in outputs if item["capability"] == capability]
        if not matching:
            continue
        smoke_validated = (
            details.get("state") == "validated" and details.get("validated") is True
        )
        installable = immutable_install_source(registry, model, details)
        reference = details.get("model_filename") or details.get("catalog_id")
        artifacts = backend_artifacts(model, details)
        install_mode = "backend_catalog" if details.get("catalog_snapshot") else "artifacts"
        contracts.append(
            {
                "id": backend_id,
                "reference": reference,
                "state": details.get("state"),
                "validated": smoke_validated,
                "smoke_validated": smoke_validated,
                "installable": installable,
                "install_mode": install_mode,
                "candidate": details.get("state") in {"listed", "validated"} and installable,
                "ready": smoke_validated and installable,
                "stable": smoke_validated and installable,
                "outputs": matching,
                "artifacts": artifacts,
                "catalog_snapshot": details.get("catalog_snapshot"),
            }
        )
    return contracts


def recommendation_entry(
    registry: dict[str, Any], models: dict[str, dict[str, Any]], capability: str
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    recommendation = registry.get("recommendations", {}).get(capability)
    diagnostic: dict[str, Any] = {"capability": capability}
    if not isinstance(recommendation, dict):
        diagnostic["reason"] = "no_recommendation"
        return None, diagnostic
    preferred_model_id = recommendation.get("model")
    preferred_model = models.get(preferred_model_id)
    if preferred_model is None:
        diagnostic["reason"] = "unknown_model"
        diagnostic["model"] = preferred_model_id
        return None, diagnostic
    candidate_specs = [
        {"model": preferred_model_id, "specialty": "recommended"},
        *recommendation.get("alternatives", []),
    ]
    candidates = []
    for spec in candidate_specs:
        candidate_model = models.get(spec.get("model"))
        if not candidate_model:
            continue
        candidate_contracts = backend_contracts(registry, candidate_model, capability)
        candidates.append(
            {
                "model": candidate_model["id"],
                "model_name": candidate_model.get("name", candidate_model["id"]),
                "specialty": spec.get("specialty"),
                "ready": any(contract["ready"] for contract in candidate_contracts),
                "backends": candidate_contracts,
            }
        )
    selected = next((candidate for candidate in candidates if candidate["ready"]), None)
    preferred_contracts = candidates[0]["backends"] if candidates else []
    if not preferred_contracts:
        reason = "missing_exact_output_contract"
    elif not any(contract["installable"] for contract in preferred_contracts):
        reason = "install_source_not_immutable"
    elif not any(contract["smoke_validated"] for contract in preferred_contracts):
        reason = "smoke_validation_pending"
    else:
        reason = "ready"
    entry = {
        "id": capability,
        "label": label_for(capability),
        "kind": kind_for(capability),
        "group": group_for(capability),
        "promoted": capability in PROMOTED_CAPABILITIES,
        "available": selected is not None,
        "recommendation": {
            "model": selected["model"] if selected else preferred_model_id,
            "model_name": (
                selected["model_name"]
                if selected
                else preferred_model.get("name", preferred_model_id)
            ),
            "preferred_model": preferred_model_id,
            "policy": recommendation.get("policy"),
            "used_fallback": bool(selected and selected["model"] != preferred_model_id),
        },
        "backends": selected["backends"] if selected else preferred_contracts,
        "candidates": candidates,
    }
    if selected and selected["model"] != preferred_model_id:
        reason = (
            "ready_via_fallback"
            if any(contract["smoke_validated"] for contract in selected["backends"])
            else "smoke_validation_pending"
        )
    diagnostic.update({"model": preferred_model_id, "reason": reason})
    return entry, diagnostic


def multitrack_entry(
    registry: dict[str, Any], models: dict[str, dict[str, Any]]
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    recommendation = registry.get("recommendations", {}).get("multitrack")
    diagnostic: dict[str, Any] = {"capability": "multitrack"}
    if not isinstance(recommendation, dict):
        diagnostic["reason"] = "no_recommendation"
        return None, diagnostic
    model_id = recommendation.get("model")
    model = models.get(model_id)
    decomposition_id = recommendation.get("decomposition")
    decomposition = model.get("decompositions", {}).get(decomposition_id) if model else None
    errors = multitrack_policy_errors(decomposition)
    if model is None:
        errors.insert(0, "unknown model")
    output_contracts: dict[str, list[dict[str, Any]]] = {}
    if isinstance(decomposition, dict):
        for capability in decomposition.get("outputs", []):
            if isinstance(capability, str) and model:
                output_contracts[capability] = backend_contracts(registry, model, capability)
                if not any(contract["ready"] for contract in output_contracts[capability]):
                    errors.append(f"{capability} has no ready exact output contract")
    diagnostic.update(
        {
            "model": model_id,
            "decomposition": decomposition_id,
            "reason": "ready" if not errors else "policy_or_readiness_failure",
            "errors": errors,
        }
    )
    if not model or not isinstance(decomposition, dict):
        return None, diagnostic
    return (
        {
            "id": "multitrack",
            "label": "Multi-Track",
            "available": not errors,
            "recommendation": {
                "model": model_id,
                "model_name": model.get("name", model_id),
                "policy": recommendation.get("policy"),
                "decomposition": decomposition_id,
            },
            "decomposition": decomposition,
            "output_backends": output_contracts,
        },
        diagnostic,
    )


def generate(registry: dict[str, Any]) -> dict[str, Any]:
    models = {model["id"]: model for model in registry.get("models", []) if "id" in model}
    capabilities = []
    diagnostics = []
    for capability in sorted(registry.get("recommendations", {})):
        if capability == "multitrack" or capability in EXCLUDED_CAPABILITIES:
            continue
        entry, diagnostic = recommendation_entry(registry, models, capability)
        diagnostics.append(diagnostic)
        if entry is not None:
            capabilities.append(entry)
    promoted_order = {capability: index for index, capability in enumerate(PROMOTED_CAPABILITIES)}
    group_order = {group: index for index, group in enumerate(GROUP_ORDER)}
    capabilities.sort(
        key=lambda item: (
            0 if item["promoted"] else 1,
            promoted_order.get(item["id"], len(promoted_order)),
            group_order.get(item["group"], len(group_order)),
            item["label"].casefold(),
        )
    )
    multitrack, multitrack_diagnostic = multitrack_entry(registry, models)
    diagnostics.append(multitrack_diagnostic)
    unavailable = [
        item
        for item in diagnostics
        if not str(item.get("reason", "")).startswith("ready")
    ]
    referenced_model_ids = {
        candidate["model"]
        for item in capabilities
        for candidate in item.get("candidates", [])
    }
    if multitrack and multitrack.get("recommendation"):
        referenced_model_ids.add(multitrack["recommendation"]["model"])
    product_models = {}
    for model_id in sorted(referenced_model_ids):
        model = models[model_id]
        product_models[model_id] = {
            "name": model.get("name", model_id),
            "architecture": model.get("architecture"),
            "status": model.get("status"),
            "availability": model.get("availability", {}),
            "backends": {
                backend_id: {
                    **{
                        key: details.get(key)
                        for key in (
                            "state",
                            "validated",
                            "model_filename",
                            "catalog_id",
                            "catalog_snapshot",
                            "artifact_names",
                        )
                        if details.get(key) is not None
                    },
                    "outputs": normalized_outputs(details),
                    "artifacts": backend_artifacts(model, details),
                }
                for backend_id, details in sorted(model.get("backends", {}).items())
                if isinstance(details, dict)
            },
        }
    return {
        "schema": 1,
        "policy": POLICY_VERSION,
        "registry_schema": registry.get("schema"),
        "generated_at": registry.get("generated_at"),
        "promoted": list(PROMOTED_CAPABILITIES),
        "groups": list(GROUP_ORDER),
        "capabilities": capabilities,
        "multitrack": multitrack,
        "models": product_models,
        "readiness": {
            "ready_capabilities": sum(item["available"] for item in capabilities),
            "stable_capabilities": sum(
                item["available"]
                and any(contract["stable"] for contract in item.get("backends", []))
                for item in capabilities
            ),
            "installable_candidates": sum(
                any(contract["candidate"] for contract in item.get("backends", []))
                for item in capabilities
            ),
            "smoke_validation_gaps": [
                {
                    "capability": item["id"],
                    "model": item["recommendation"]["model"],
                }
                for item in capabilities
                if not item["available"]
                and any(contract["candidate"] for contract in item.get("backends", []))
            ],
            "unavailable": unavailable,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, default=ROOT / "registry.json")
    parser.add_argument("--output", type=Path, default=ROOT / "product-catalog.json")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = json.dumps(generate(load(args.registry)), indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if not args.output.is_file() or args.output.read_text(encoding="utf-8") != rendered:
            raise RuntimeError(f"Generated product catalogue is stale: {args.output}")
    else:
        args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
