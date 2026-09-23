"""Build a static, synthetic-data demo from the real UI. No backend or user data."""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "_site"
STATIC = ROOT / "pcspace" / "static"


def build() -> Path:
    OUT.mkdir(exist_ok=True)
    dest = OUT / "static"
    dest.mkdir(exist_ok=True)
    for name in ("app.js", "demo.js", "app.css", "icon.svg"):
        shutil.copy2(STATIC / name, dest / name)
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    html = html.replace('<html lang="ko"', '<html lang="en" data-demo="true"', 1)
    (OUT / "index.html").write_text(html, encoding="utf-8")
    (OUT / ".nojekyll").touch()
    return OUT


if __name__ == "__main__":
    print(build())
