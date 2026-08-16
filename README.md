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
license. The registry records those terms where they are known; an `unknown`
license is a prompt for further review, not a grant of permission.

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

## License

The registry and its supporting code are available under the
[MIT License](LICENSE). This license does not grant rights to any model weights,
datasets, or other third-party materials referenced by the registry.
