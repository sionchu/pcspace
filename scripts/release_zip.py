"""Package only version-controlled files. Never package the working directory recursively."""
from pathlib import Path
import hashlib
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def build() -> Path:
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    version = (ROOT / "pcspace" / "__init__.py").read_text().split('"')[1]
    output = ROOT / "dist" / f"PCSpace-{version}-source.zip"
    output.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as z:
        for name in filter(None, tracked):
            p = Path(name)
            if p.is_absolute() or ".." in p.parts or p.name in {"policy.json", "access-key.txt", ".env"}:
                raise ValueError(f"Unsafe release path: {name}")
            if p.suffix in {".sqlite3", ".db", ".b64"} or any(part in {".deps", ".venv", "browser-results"} for part in p.parts):
                raise ValueError(f"Runtime file in Git index: {name}")
            z.write(ROOT / name, "PCSpace/" + name)
    files = sorted(p for p in output.parent.iterdir() if p.is_file() and p.name != "SHA256SUMS.txt")
    (output.parent / "SHA256SUMS.txt").write_text("\n".join(hashlib.sha256(p.read_bytes()).hexdigest() + "  " + p.name for p in files) + "\n")
    return output


if __name__ == "__main__":
    print(build())
