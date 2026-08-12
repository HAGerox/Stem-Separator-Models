# Hermes maintenance instructions

Hermes runs privately, polls online sources and opens GitHub pull requests. GitHub does not call Hermes and requires no route into Tailscale.

## Evidence priority

1. Use the Deton24 guide as the primary qualitative catalogue and sentiment source.
2. Use MVSep as the primary measured benchmark source.
3. Use original model repositories, Hugging Face and separator catalogues for artifacts, hashes, licences and compatibility.
4. Never treat another project's recommendation order as this registry's ranking.
5. Never add a model that can only be run through a hosted provider.

## Scheduled run

1. Update the repository.
2. Read enabled entries in `sources.json`, including the python-audio-separator, pymss and MVSepLess machine-readable catalogues.
3. Export sources and compare them with private prior snapshots.
4. Extract new models, changed claims and measured results.
5. Update factual model records and structured evidence.
6. Re-evaluate only the affected recommendation tasks under the registry policy.
7. Run `python3 scripts/validate.py`.
8. Run `python3 scripts/pr_body.py --base-ref origin/main --output PR_BODY.md`.
9. Open a PR with `gh pr create --body-file PR_BODY.md`.

Source snapshots and hashes may remain in Hermes' private storage. The public registry stores the source URL, stable entry URL where available, and document line range used for each observation.

## Measured benchmarks

Copy values exactly and leave unavailable metrics absent:

```json
{
  "suite": "mvsep-multisong-v1",
  "stem": "instrumental",
  "values": {
    "sdr_db": 17.5466,
    "si_sdr_db": 17.4497,
    "mvsep_bleedless": 41.3606,
    "mvsep_fullness": 34.2534
  },
  "source": "https://mvsep.com/quality_checker/entry/9482",
  "config": {}
}
```

Rules:

- Compare results only when suite, dataset, stem mapping and protocol match.
- Preserve MVSep metrics independently; do not collapse them into SDR.
- Create a new versioned suite when the dataset or protocol changes.
- Never infer or average missing measurements.
- Keep source-reported non-standard metrics in a suite marked `standardized: false`.

## Qualitative extraction

Translate only explicit source sentiment into `semantic_evidence`:

```json
{
  "id": "model-id-deton24-1",
  "task": "vocals",
  "method": "llm_derived",
  "values": {
    "bleed_control": 82,
    "fullness_preservation": 71,
    "artifact_control": 76,
    "robustness": 70,
    "tonal_fidelity": 78
  },
  "confidence": 0.74,
  "source_id": "deton24-google-doc-YYYY-MM-DD",
  "source": "https://docs.google.com/document/d/...",
  "location": {
    "line_start": 100,
    "line_end": 130
  },
  "tags": ["low_bleed", "fullness_tradeoff"]
}
```

Use the semantic scale in `registry.json`. Scores describe the cited statements, not an LLM's unaided opinion. Confidence measures clarity and evidence coverage, not quality. Keep measured and semantic evidence separate.

## Recommendation rules

- Apply the declared task weights; never sort only by SDR.
- Missing evidence reduces coverage and is never treated as zero.
- `model` must have public weights/configuration and a credible local inference path.
- Provider-only models and ensembles are evidence only and never recommendation candidates.
- Compatibility and availability do not increase a model's quality score.
- Keep useful historical models in the registry even when they are no longer selected.
- Change no more than one recommendation task per PR.
- A factual model/evidence PR may precede independent recommendation PRs for each affected task.

## Artifact and compatibility rules

- Require a public artifact repository and at least one local backend path for every model.
- Use immutable artifact revisions where possible.
- Record SHA-256 hashes when artifacts have been downloaded and verified.
- Store uncertain licences as `unknown`; never infer a permissive licence from public availability.
- Do not mark a backend `validated` without an exact-checkpoint smoke test.
- Architecture similarity alone does not establish MLX compatibility.
- Never invent a URL, revision, hash, licence, benchmark or backend result.

## Listening comparison

Only manually dispatch the evaluation workflow for a recommendation PR whose current and proposed models have an evaluator-supported listed backend (`audio_separator` or `pymss`). It compares one task against the current registry using the private configured tracks. The generated PR body lists the exact test files and artifact link.
