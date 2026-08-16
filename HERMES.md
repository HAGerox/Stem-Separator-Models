# Hermes maintenance instructions

Hermes privately checks the configured sources about once a month and opens reviewable GitHub pull requests. GitHub does not call Hermes and requires no private network access.

## Goal

Keep the registry current without requiring an app update when models change. A model is usable by the product only when its exact public artifacts and outputs have passed the pinned Python Audio Separator runtime.

The registry contains facts and evidence. Maintenance policy lives in the Python scripts and this document, not as prose or scoring rules inside `registry.json`.

## Monthly review

1. Update the repository and read every enabled entry in `sources.json`.
2. Compare current source snapshots with the previous private snapshots.
3. Find new models, releases, artifacts, benchmark results and changed qualitative claims.
4. Confirm the original repository or Hugging Face release, immutable revision, licence, checkpoint, configuration and SHA-256 hashes.
5. Confirm the model can run through the pinned Python Audio Separator architecture. Do not admit models that require another runtime, hosted service or custom unsupported model code.
6. Record every exact model output. Map a friendly capability to a runtime output only when the source or configuration establishes that relationship; never infer aliases such as `hihat` and `hh` from spelling alone.
7. Add an executable but untested model as `compatible_unvalidated`. Never set `validated` manually.
8. Add measured and ordinal evidence from the sources, then re-rank only affected tasks.
9. Change at most one selected recommendation in a PR. Factual updates and alternatives may be grouped together.
10. Generate and validate the proposed data:

   ```sh
   python3 scripts/product_catalog.py
   python3 scripts/validate.py
   python3 -m unittest discover -s tests
   python3 scripts/pr_body.py --base-ref origin/main --output PR_BODY.md
   ```

11. Open the PR with `gh pr create --body-file PR_BODY.md` and let CI perform runtime validation and any required listening comparison.

Source snapshots and hashes may remain in Hermes' private storage. Public evidence must retain a stable source URL and a precise source location.

## Evidence and ranking

Copy measured benchmark values exactly. Compare them only when the suite, dataset, stem definition and protocol match. Preserve source-specific metrics separately and leave unavailable values absent.

Qualitative evidence is ordinal:

- Record only explicit, source-attributed comparisons between models.
- Keep each comparison tied to its task, metric, context and source location.
- Preserve ties, conflicts and incomparable models instead of manufacturing a total order.
- Do not translate prose into a 0–100 score or mechanically convert old scores.
- Do not turn a source's recommendation order into this registry's ranking.

Use `scripts/rank.py` to inspect the evidence fronts for an affected task. Missing evidence means unobserved, not zero. Compatibility and popularity do not increase quality.

The selected recommendation should be supported across the relevant evidence contexts. When the evidence does not establish a better replacement, retain the incumbent. A new selection must be compared against the incumbent using the private listening suite before merge.

## Model admission

Every admitted model must have:

- a public, immutable checkpoint and required configuration;
- verified SHA-256 hashes;
- a Python Audio Separator backend contract;
- exact runtime output keys and registry capabilities;
- a licence recorded from evidence, or `unknown` when it cannot be established.

Models that are restoration-only, provider-only, unsupported by Python Audio Separator, or impractical for the product's target hardware do not belong in the registry. Do not invent URLs, revisions, hashes, licences, outputs, compatibility or benchmark results.

Multi-Track is reserved for a useful general-music decomposition. Specialist drum splits and large collections of overlapping instruments are independent stem extractors, not Multi-Track. Reconstruction is a separate capability and must not be claimed from a short loader smoke.

## Automatic pull-request checks

Ordinary CI validates the schema, evidence, policy, generated product catalogue and recommendation delta.

The Audio Separator smoke workflow then tests every `compatible_unvalidated` model using its pinned checkpoint and configuration. It also re-tests prior smoke-evidenced models whenever the pinned runtime changes. It verifies hashes, exact output filenames and structurally valid stereo WAV output. Passing models are promoted automatically and the product catalogue is regenerated. Failed models remain unavailable and block the PR. Silence in one specialist output is allowed because the deterministic fixture may not contain that target; this check establishes runtime compatibility rather than quality.

If the PR changes one selected recommendation, the private listening comparison runs automatically after the proposed model passes its smoke. It adds the comparison artifact to the PR for human review. Do not manually bypass either check.

After approval and merge, the app and server fetch the generated product catalogue. Only validated, installable capabilities are exposed; unsupported or failed models remain hidden without requiring an app code change.
