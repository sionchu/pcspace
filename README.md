# PCSpace

**See what takes up space. Decide what stays.**

A local-first, directory-first storage explorer for Windows. Explore an interactive treemap from large folders down to individual files, review cleanup hints, and recycle or delete only what you select.

> Early public alpha. This repository contains application source and synthetic tests, not anyone's files, scan database, or access settings. Public source does not expose your PC to the internet.

## Run from source

Requires Windows 10/11 and Python 3.12 or newer.

```powershell
git clone https://github.com/sionchu/pcspace.git
cd pcspace
python -m pip install -r requirements.txt
python -m pcspace --open
```

Open `http://127.0.0.1:8768`. No extra password on your own PC. Keep the terminal open; Ctrl+C stops the server. Optional remote use requires private Tailscale Serve and an explicit owner allowlist; do not use Funnel or public port forwarding.

## Scope

Directory-first scans, live progress, pause/resume, cleanup hints, one-confirmation recycle/permanent delete, operation history, stale-folder handling, and WSL disk explanations. Sizes are logical bytes, not guaranteed reclaimable space. Candidate labels do not mean a file is disposable. Permanent deletion cannot be undone.

The interface is currently Korean. Packaging, public documentation, and visual refinements are being prepared for the first tagged release.

MIT licensed. See [LICENSE](LICENSE) and [TEST_REPORT.md](TEST_REPORT.md).
