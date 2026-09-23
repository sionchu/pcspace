"""Create an isolated environment on first launch, then open the local app."""
from __future__ import annotations
import hashlib
from pathlib import Path
import subprocess
import sys


def main() -> int:
    if sys.platform != "win32":
        print("The desktop release supports Windows. See README for development on other platforms.")
        return 1
    if sys.version_info < (3, 12):
        print("Python 3.12 or newer is required. Install Python, then run Start-PCSpace.cmd again.")
        return 1
    root = Path(__file__).resolve().parent
    env = root / ".venv"
    python = env / "Scripts" / "python.exe"
    try:
        if not python.exists():
            print("Creating PCSpace's private Python environment (no administrator rights required)…")
            subprocess.run([sys.executable, "-m", "venv", str(env)], check=True)
        digest = hashlib.sha256((root / "pyproject.toml").read_bytes() + (root / "pcspace" / "__init__.py").read_bytes()).hexdigest()
        marker = env / ".pcspace-install"
        if not marker.exists() or marker.read_text() != digest:
            print("Installing PCSpace dependencies into .venv; internet is needed for this step.")
            subprocess.run([str(python), "-m", "pip", "install", "--disable-pip-version-check", "."], cwd=root, check=True)
            marker.write_text(digest)
        return subprocess.call([str(python), "-m", "pcspace", "--open"], cwd=root)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"PCSpace could not start: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
