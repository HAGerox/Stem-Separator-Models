# Contributing

Contributions should be factual, source-attributed and narrowly scoped.

- Add only models with publicly downloadable weights/configuration and a credible local inference path.
- Use immutable artifact revisions and SHA-256 hashes when they have been independently verified.
- Record uncertain licences as `unknown`; public availability does not imply permission to redistribute or use commercially.
- Keep measured and qualitative evidence separate, and never invent or fill missing metrics.
- Change no more than one recommendation task per pull request unless replacing the full baseline schema.
- Do not commit source snapshots, private evaluation audio, identifying private filenames, credentials or generated listening results.

Run before opening a pull request:

```bash
python3 scripts/validate.py
python3 -m py_compile scripts/*.py
```
