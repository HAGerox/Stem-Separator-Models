# Stem Separator Models

Stem Separator Models is the curated model registry that powers
[Stem Separator](https://github.com/HAGerox/Stem-Separator). It helps the app
choose a strong model for each requested stem without requiring users to
compare checkpoints, benchmarks, and runtime support themselves.

The registry covers vocals, instrumentals, drums, bass, guitar, piano, and
other specialist separation tasks. It contains model information,
compatibility details, supporting evidence, and balanced recommendations.

## Principles

- Models must have publicly downloadable weights and a credible local runtime.
- Recommendations consider several quality signals rather than a single score.
- Measured results and qualitative evidence remain source-attributed.
- Missing or uncertain information is left unknown instead of being guessed.
- Changes are validated automatically and reviewed by a maintainer.

Publicly downloadable weights are not necessarily open source. Each model has
its own license and usage terms, which are separate from this repository's
license. The registry records those terms where they are known.

## Using the registry

[`registry.json`](registry.json) is the app-facing data file. It can be fetched
directly from GitHub and cached locally; no API service or database is needed.
[`sources.json`](sources.json) records the sources monitored when maintaining
the registry.

Stem Separator keeps a bundled snapshot for offline use and periodically
checks this repository for updated recommendations.

## For maintainers

Validate changes with:

```bash
python3 scripts/validate.py
python3 -m py_compile scripts/*.py
```

Private registry maintenance guidance is kept in [`HERMES.md`](HERMES.md).

Runtime smoke and listening checks install the pinned Audio Separator revision
with `librosa==0.10.2.post1`. Its audio writer uses the `filename` duration
argument removed in librosa 1.0. Keep the compatibility constraint when
reproducing those checks. Smoke artifacts include reports and output audio;
staged checkpoints stay on the disposable runner and are not uploaded again.

## Workflow security

Automatic checks are reserved for PRs authored by HAGerox from a branch in this
repository to `main`. The privileged workflows also require HAGerox to trigger
the run; manual runs must use the workflow on `main` and satisfy the same PR
authorization. Authorization uses immutable GitHub user and repository IDs.
Fork PRs and other authors are rejected, including on manual runs. Write jobs
recheck that the PR is still open and its base and head have not changed.

Runtime workflows execute scripts from `main` and read only the proposed
registry JSON. Model execution has read-only repository permissions on disposable
GitHub-hosted runners. Writing promotions or PR comments happens in separate jobs
that do not install or load model runtimes. Promotion commits are built without
checking out the PR tree. Checkout credentials and shared dependency/model caches
are disabled. Downloads require safe filenames, SHA-256 verification, allowed
HTTPS hosts at every redirect, and size limits (1 MiB for config, 8 GiB for weights).

In **Settings → Actions → General**, keep approval required for **all external
contributors**, SHA pinning required, and only the exact action commits in these
workflows allowed. Do not approve outside workflow runs: a fork can change its own
`pull_request` workflow, so a job condition alone cannot enforce this policy.
Review action allowlist updates whenever pinned commits change.
The `main` branch requires a PR and a passing GitHub Actions `validate` check;
force pushes and deletion are blocked, including for administrators.

Public model hosting and a matching checksum do not establish that a model is
safe. Review artifact provenance before adding a checkpoint. Model parsers,
Python dependencies, and hosted runner images remain supply-chain trust boundaries;
no workflow configuration can guarantee zero risk.

## License

The registry and its supporting code are available under the
[MIT License](LICENSE). This license does not grant rights to any model weights,
datasets, or other third-party materials referenced by the registry.
