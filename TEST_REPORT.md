# Validation

PCSpace is an early Windows-focused release, not a backup tool or a security boundary against software running as the same OS user.

## Baseline: 0.2.1

On a Windows 11 development machine: `python -m pytest -q -rs` reported **32 passed, 1 skipped**. The skipped scenario required Windows symlink creation permission. The Chrome/CDP fixture suite reported **14 checks passed**, including native recycle, permanent delete, preserved unselected files, and a 390px mobile viewport. These tests use generated disposable data only.

Tests include directory aggregates, 500,010 synthetic entries without the old file cap, pause/resume, authentication boundaries, changed-path rejection, single confirmation, missing-folder redirects, and WSL package hints. Synthetic throughput does not predict real drive performance.

## Reproduce

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q -rs
node tests/ui_state_test.mjs
node tests/browser_e2e.mjs
```

The browser suite requires Node 22+ and Chrome/Edge. Set `PCSPACE_TEST_PYTHON` or `PCSPACE_TEST_CHROME` for a custom executable. Linux can run core tests, but native Windows recycle is Windows-only. Do not interpret Linux tests as desktop support.

## Known limits

The scanner measures logical size. Hardlinks, compressed files and sparse disks can differ from actual disk allocation. External changes and changes during a running scan can leave totals stale; missing paths are filtered on navigation. Recycle contents still occupy disk space. Permanent deletion has no application undo. Complex reparse points, cloud providers and adversarial concurrent filesystem changes are not exhaustively verified.

No private scan data, local deployment records, real screenshots, keys, or personal network settings are part of the public repository.
