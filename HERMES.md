# Hermes maintenance instructions

Hermes runs privately and opens GitHub pull requests. GitHub does not call Hermes.

## Scheduled run

1. Update the repository.
2. Read enabled entries in `sources.json`.
3. Compare those sources with `registry.json` and previous private snapshots.
4. Research changed models, benchmark results and recommendations.
5. Update `registry.json`.
6. Run `python3 scripts/validate.py`.
7. Run `python3 scripts/pr_body.py --output PR_BODY.md`.
8. Open a PR using `gh pr create --body-file PR_BODY.md`.

Hermes may retain source exports and hashes outside this repository.

## Numerical benchmarks

Put comparable numerical results in `benchmarks`:

```json
{
  "stem": "instrumental",
  "suite": "mvsep-multisong-v1",
  "values": {
    "sdr_db": 17.55,
    "snr_db": 18.12
  },
  "source": "https://..."
}
```

Rules:

- Results are directly comparable only when `suite` matches.
- Create a new versioned suite ID when the dataset or protocol changes.
- Copy values exactly; never infer missing numerical measurements.
- Keep separate results from separate suites.
- Do not average results across suites.

## Converting qualitative material

Convert useful sentiment from guides and documents into `quality` observations:

```json
{
  "stem": "vocals",
  "method": "llm_derived",
  "values": {
    "bleed_control": 82,
    "fullness": 71,
    "artifact_control": 76
  },
  "confidence": 0.74,
  "source": "https://..."
}
```

All quality metrics are 0–100 and higher is better.

- `bleed_control`: 0 means severe unwanted-source bleed; 100 means effectively isolated.
- `fullness`: 0 means substantial desired-source loss; 100 means complete desired-source capture.
- `artifact_control`: 0 means severe processing artifacts; 100 means effectively artifact-free.

Use `method` as follows:

- `source_score`: normalize an explicit score supplied by the source.
- `llm_derived`: translate qualitative source language using the rubric above.
- `listening_test`: derive from this repository's maintained listening test.

Confidence is 0–1 and reflects source clarity and coverage, not model quality. Preserve separate observations from separate sources. Do not silently combine them into a single score.

## PR rules

- A recommendation PR changes exactly one recommendation model.
- A model/benchmark PR may update related factual records without changing a recommendation.
- Open separate recommendation PRs for vocals and instrumental.
- Do not mark a backend as tested without a completed run.
- Do not invent URLs, hashes, licences or measured benchmark values.
- The generated PR body is authoritative; avoid adding narrative sections.

