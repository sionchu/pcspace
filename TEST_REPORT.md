# PCSpace 0.3.0 validation

Recorded 2026-09-24. Public alpha, not a backup tool or an independently audited security product.

## Executed before publication

| Environment | Result |
| --- | --- |
| Windows 11, Python 3.12, fresh isolated dependencies | 35 passed, 1 skipped (7.89 seconds) |
| Windows skip | Symlink creation unavailable under the test account's Windows policy |
| Linux development environment, Python 3.13 | 35 passed, 1 skipped (Windows-native recycle) |
| Real Windows Chrome / CDP | 20 checks passed |
| Treemap and UI state | 59 geometry scenarios and stale-response handling passed |
| Read-only demo | Totals, two drives, mutation rejection, and no backend dependency passed |

The browser test checks local automatic sessions, actual fixture scans, treemap navigation, one-confirmation native recycle and permanent deletion, preserved unselected files, activity history, and a 390px mobile viewport. Public-demo checks cover English/Korean, dark mode, no real API requests, and disabled cleanup. Mobile testing is viewport emulation, not a physical phone.

Public screenshots were captured from synthetic demo data. The separate filesystem regression fixture and real machine paths are not published.

## Reproduce

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q -rs
node tests/ui_state_test.mjs
node tests/demo_test.mjs
node tests/browser_e2e.mjs
```

Node 22+ and installed Chrome/Edge are needed for the browser suite. Set `PCSPACE_TEST_PYTHON` and `PCSPACE_TEST_CHROME` when executables are not on their usual paths. CI definitions test Windows/Linux with Python 3.12/3.13; their actual run status is linked from the repository Actions tab rather than assumed from local results.

## Important limits

The 500,010-entry scan test is synthetic and demonstrates removal of the old cap, not a real-drive speed claim. Sizes are logical bytes; hardlinks, compression and sparse disks can differ from allocation or reclaimable capacity. Scans can become stale during external changes. Recycle contents occupy disk space until emptied. Permanent deletion has no app undo. Unknown cloud providers and malicious concurrent file replacement are not exhaustively verified. A same-user process can bypass app-level safeguards. See SECURITY.md.

Current third-party test dependencies emit an AnyIO/Starlette deprecation warning; this did not fail the tests. No claim is made that the code is warning-free.

## Hosted CI verification

[CI run 35895822482](https://github.com/sionchu/pcspace/actions/runs/35895822482) passed all four jobs (Windows/Linux, Python 3.12/3.13), including package builds. [Demo deployment 35895822468](https://github.com/sionchu/pcspace/actions/runs/35895822468) succeeded; the published demo HTML and its JavaScript/CSS returned HTTP 200. These runs tested commit f4c4489; the subsequent change is this validation note and the source-download wording.
