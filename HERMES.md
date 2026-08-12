# Hermes maintenance instructions

Hermes runs on the maintainer's private network and opens pull requests from there. GitHub Actions must not call Hermes.

## Scheduled job

On a daily or weekly schedule:

1. Clone or update this repository.
2. Read `sources.json`.
3. Compare each enabled source with the information currently represented in `registry.json`.
4. Investigate meaningful changes, following direct links to model repositories and files where necessary.
5. Update the database only when the source supports the change.
6. Run `python3 scripts/validate.py`.
7. Open a pull request with a concise summary and source links.

Hermes may keep page hashes, exported documents, and previous snapshots in its own working directory. They do not need to be committed here.

## Pull request rules

- A metadata-only PR may add or correct multiple closely related facts.
- A recommendation PR changes exactly one stem under `recommendations`.
- If one model may improve vocals and instrumental, open two recommendation PRs.
- Do not mark a model as tested unless an actual backend run was performed.
- Do not invent benchmark values, hashes, licences, publication dates, or compatibility claims.
- Prefer a pinned model URL and SHA-256 when the upstream source provides a stable downloadable artifact.
- Link every non-obvious claim to a public source.

## Suggested PR body

```text
## Change

- Added/updated ...

## Why

- Source A says ...
- Source B reports ...

## Verification

- [x] registry validation passed
- [ ] model was run with audio-separator
- [ ] model was run with MLX
- [ ] listening comparison attached
```

