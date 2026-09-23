# Contributing

Small, testable changes are welcome. Open an issue describing the user problem before a large redesign.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pytest -q -rs
node tests/ui_state_test.mjs
node tests/demo_test.mjs
```

Use only disposable fixtures in filesystem tests. Do not test deletion on real Downloads, projects, backup folders or system data. Keep scanner operations metadata-only. Preserve one explicit confirmation for a selected set; never add an automatic purge or a silent permanent-delete fallback.

Keep dependencies in `pyproject.toml`, UI assets in `pcspace/static`, and data in the local state directory. The demo is generated from the same UI, not a separate mock application. Do not add private state, local deployment notes, credentials, real scan reports or personal screenshots to a pull request.

Windows is the supported desktop platform. Linux CI validates portable core logic only. Include platform-specific tests for changes to Windows recycle, path handling and process behavior.
