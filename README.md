# Stem Separator Models

A small, maintainer-curated registry of locally runnable stem-separation models, evidence and recommendations.

The project follows the useful part of [Privacy Guides' Verified Apps](https://github.com/privacyguides/verified-apps): the product is a simple, reviewable data file. Automation validates it and prepares structured changes; maintainer judgement remains the trust boundary.

## Repository

```text
registry.json                    App-facing models, evidence and recommendations
sources.json                     Sources monitored by the private Hermes agent
scripts/validate.py              Dependency-free registry validation
scripts/pr_body.py               Structured PR-body generator
scripts/evaluate.py              Optional candidate-versus-current listening test
evaluation/tracks.json           Public empty template for the private runner manifest
.github/workflows/ci.yml         Validation on pushes and PRs
.github/workflows/evaluate.yml   Optional self-hosted listening comparison
HERMES.md                        Private agent maintenance instructions
CONTRIBUTING.md                  Public contribution and data-quality rules
SECURITY.md                      Private vulnerability reporting guidance
```

There is no generated directory, API service or database. Apps can fetch `registry.json` directly from GitHub and cache it with `ETag` / `If-None-Match`.

The registry contains only models with publicly downloadable weights/configuration and a credible local inference path. Provider-only models and hosted ensembles are excluded. Services such as MVSep may still appear as benchmark or qualitative evidence sources.

`scope` makes this contract machine-readable:

```json
{
  "execution": "local_only",
  "weights": "publicly_downloadable",
  "provider_only_models": false,
  "license_metadata_required": true
}
```

Publicly downloadable weights are not necessarily permissively licensed. Apps should expose and filter each model's `availability.license`; `unknown` means the licence still requires verification.

## Evidence model

The initial baseline covers current, specialist and historical models across vocal/instrumental separation, karaoke, drum and drum-substem separation, bass, four/six/many-stem output, guitars, piano, strings and bowed strings, choir, winds, brass, trumpet, saxophone, synth, organ, bells, percussion and restoration tasks.

The two primary evidence sources have different jobs:

- MVSep supplies measured results such as SDR, SI-SDR, L1 frequency, Log-WMSE, Aura STFT/MRSTFT, bleedless and fullness. Results are comparable only within the same `benchmark_suites` entry.
- The Deton24 guide supplies qualitative observations. Hermes converts its descriptions into source-attributed 0–100 `semantic_evidence` fields such as bleed control, fullness preservation, artifact control, robustness and tonal fidelity.

Other sources, including python-audio-separator, pymss, MVSepLess resources, MLX projects and Hugging Face, supply artifact and local-compatibility metadata. They are not treated as quality rankings.

Missing values are omitted. They are never filled with zero, and missing evidence reduces coverage rather than model quality.

Example measured result:

```json
{
  "suite": "mvsep-multisong-v1",
  "stem": "instrumental",
  "values": {
    "sdr_db": 17.5466,
    "mvsep_bleedless": 41.3606,
    "mvsep_fullness": 34.2534
  },
  "source": "https://mvsep.com/quality_checker/entry/9482",
  "config": {}
}
```

Example structured qualitative evidence:

```json
{
  "task": "instrumental",
  "method": "llm_derived",
  "values": {
    "bleed_control": 88,
    "fullness_preservation": 82,
    "artifact_control": 76
  },
  "confidence": 0.72,
  "source_id": "deton24-google-doc-2026-08-12",
  "source": "https://docs.google.com/document/d/17fjNvJzj8ZGSer7c7OFe_CNfUKbAxEh_OBv94ZdRG5c/edit?usp=sharing",
  "location": {
    "line_start": 6955,
    "line_end": 7200
  },
  "tags": ["all_rounder"]
}
```

## Recommendations

Every recommendation points directly to a locally runnable public-weight model:

```json
{
  "policy": "balanced-quality-v1",
  "model": "becruily-deux",
  "alternatives": [
    {
      "model": "bs-roformer-leap-xe",
      "specialty": "bleed_control"
    }
  ]
}
```

- `model` is the recommended locally runnable model.
- `alternatives` expose task-specific trade-offs without maintaining explanatory paragraphs.

The versioned policy combines multiple measured and semantic components; it does not sort by SDR alone. Its declared measured and semantic class weights are validated against the per-task metric weights. Tasks without an explicit weight set use the declared `default_task_weights` entry (`specialist` in the current policy). Public weights and a local runtime are eligibility requirements, not score bonuses.

Deprecated models are not eligible as default recommendations. An experimental model can only fill a task when no non-experimental public-weight candidate supports it; apps should inspect the selected model status and present that recommendation as opt-in rather than production-ready.

For multitrack recommendations, `delivery.mode: residual_to_stem` tells an app to calculate the difference between the input and the raw stem sum and add it to `other`. The delivered stems therefore sum to the original audio even when the model's raw outputs do not.

## Maintenance flow

Hermes is private and reachable only by the maintainer. GitHub never invokes it.

```text
Hermes polls sources.json
        ↓
diffs private source snapshots
        ↓
LLM extracts candidate factual and semantic changes
        ↓
updates registry.json on a branch
        ↓
scripts/validate.py + scripts/pr_body.py
        ↓
Hermes opens a structured GitHub PR
        ↓
CI and maintainer review
```

Use one recommendation task per PR. A newly added model and its evidence can be introduced first, followed by independent `vocals` and `instrumental` recommendation PRs. That lets the maintainer accept one result and reject the other without partial merges or stacked-PR machinery.

The optional self-hosted evaluation workflow runs only when manually dispatched. The committed `evaluation/tracks.json` is an empty public template; the runner keeps its real filenames in ignored `evaluation/tracks.local.json`. It compares the current and proposed local recommendation through listed `audio_separator` or `pymss` backends, then attaches the resulting audio/HTML artifact to the PR. Copyrighted tracks, identifying filenames and rendered audio are not committed.

## Security and publication

Before publishing or mirroring the repository, scan the current tree and all Git history with a secret scanner. Normal publication should push `main` (and intentional release tags) only; do not mirror local tool/checkpoint refs. GitHub Actions are pinned to immutable commit SHAs, workflows use least-privilege permissions, and the self-hosted evaluation job can only be started manually by a repository collaborator.

Run the required local checks with:

```bash
python3 scripts/validate.py
python3 -m py_compile scripts/*.py
```
