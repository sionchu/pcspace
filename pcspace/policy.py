"""Filesystem boundaries, lightweight hints, and execution snapshots."""
from __future__ import annotations
import hashlib
import json
import os
import stat
import time
from pathlib import Path

REPARSE = 0x400
CLOUD = 0x1000 | 0x40000 | 0x400000
SYSTEM = 0x4
INSTALL_EXTS = {".exe", ".msi", ".msix", ".iso", ".zip", ".7z", ".rar", ".tar", ".gz"}
CLOUD_PREFIXES = ("onedrive", "iclouddrive", "icloudphotos", "icloud", "dropbox", "google drive", "googledrive")

class PolicyError(ValueError):
    pass


def inside(path: Path, root: Path) -> bool:
    """Component-aware, case-insensitive on Windows; not a string-prefix test."""
    try:
        return os.path.commonpath((os.path.normcase(str(path)), os.path.normcase(str(root)))) == os.path.normcase(str(root))
    except ValueError:
        return False


def canonical(raw: str | Path) -> Path:
    s = os.fspath(raw)
    if not s or "\x00" in s or any(ord(c) < 32 for c in s):
        raise PolicyError("잘못된 경로입니다.")
    p = Path(os.path.abspath(os.path.expanduser(s)))
    if os.name == "nt":
        if s.startswith(("\\\\", "//")) or ":" in str(p)[2:]:
            raise PolicyError("네트워크·장치·대체 데이터 스트림 경로는 지원하지 않습니다.")
        if any(x.endswith((" ", ".")) for x in p.parts[1:]):
            raise PolicyError("모호한 Windows 경로는 허용하지 않습니다.")
    return p


def snapshot(p: Path) -> dict:
    s = p.stat(follow_symlinks=False)
    return {"size": s.st_size, "mtime_ns": s.st_mtime_ns, "ctime_ns": s.st_ctime_ns,
            "dev": str(s.st_dev), "ino": str(s.st_ino), "nlink": s.st_nlink,
            "attrs": getattr(s, "st_file_attributes", 0), "mode": s.st_mode}


def unchanged(p: Path, expected: dict) -> dict:
    actual = snapshot(p)
    for key in ("size", "mtime_ns", "ctime_ns", "dev", "ino", "nlink", "attrs", "mode"):
        if actual.get(key) != expected.get(key):
            raise PolicyError("스캔/계획 이후 파일이 변경되었습니다. 다시 스캔해 주세요.")
    return actual


def guard_chain(p: Path, allow_missing_leaf: bool = False) -> None:
    """Reject symlinks, junctions, cloud placeholders in every existing component."""
    for part in (*reversed(p.parents), p):
        try:
            s = part.stat(follow_symlinks=False)
        except FileNotFoundError:
            if allow_missing_leaf and part == p:
                continue
            raise PolicyError("경로가 존재하지 않습니다.")
        a = getattr(s, "st_file_attributes", 0)
        if stat.S_ISLNK(s.st_mode) or a & (REPARSE | CLOUD):
            raise PolicyError("링크·정션·클라우드 경로는 일반 작업에서 제외됩니다.")


class Policy:
    """Only actual system/credential/cloud boundaries block deletion; other labels warn."""
    def __init__(self, state: Path, roots: list[str] | None = None):
        self.state = canonical(state)
        self.state.mkdir(parents=True, exist_ok=True)
        self.path = self.state / 'policy.json'
        if not self.path.exists():
            roots = roots or ([d+':\\' for d in 'CD' if Path(d+':/').is_dir()] if os.name == 'nt' else [str(Path.home())])
            self.data = {'version': 2, 'allowed_roots': roots, 'protected_paths': [str(self.state), str(Path(__file__).resolve().parent.parent)],
                         'cloud_paths': [], 'origins': ['http://127.0.0.1:8768','http://localhost:8768'],
                         'tailnet_users': [], 'large_bytes': 512*1024**2, 'stale_days': 90, 'temp_days': 7}
            self.save()
        self.reload()

    def reload(self):
        self.data = json.loads(self.path.read_text(encoding='utf-8'))
        self.roots = [canonical(p) for p in self.data['allowed_roots']]
        self.protected = [canonical(p) for p in self.data['protected_paths']]
        self.clouds = [canonical(p) for p in self.data['cloud_paths']]
        for key in ('OneDrive','OneDriveConsumer','OneDriveCommercial'):
            if os.environ.get(key):
                self.clouds.append(canonical(os.environ[key]))
        self.hard = list(self.protected)
        home = Path.home()
        self.hard += [home / n for n in ('.ssh','.aws','.azure','.gnupg')]
        if os.name == 'nt':
            self.hard += [canonical(os.environ.get('SystemRoot',r'C:\Windows')),
                          canonical(os.environ.get('ProgramFiles',r'C:\Program Files')),
                          canonical(os.environ.get('ProgramFiles(x86)',r'C:\Program Files (x86)')),
                          canonical(os.environ.get('ProgramData',r'C:\ProgramData'))]
        self._hardstrings = [os.path.normcase(str(p)) for p in self.hard]
        self._cloudstrings = [os.path.normcase(str(p)) for p in self.clouds]

    def save(self):
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.data,ensure_ascii=False,indent=2),encoding='utf-8')
        os.replace(tmp,self.path)

    @property
    def digest(self):
        return hashlib.sha256(json.dumps(self.data,sort_keys=True).encode()).hexdigest()

    def allowed(self, raw, existing=True):
        p = canonical(raw)
        if not any(inside(p,r) for r in self.roots):
            raise PolicyError('허용된 로컬 드라이브 밖입니다.')
        if existing:
            guard_chain(p)
        return p

    def cloud(self,p):
        return any(inside(p,r) for r in self.clouds) or any(x.casefold().startswith(CLOUD_PREFIXES) for x in p.parts)

    def skip_directory(self,p):
        if self.cloud(p):
            return '클라우드 동기화 폴더'
        if any(inside(p,r) for r in self.hard):
            return '시스템·인증정보·직접 지정한 보호 경로'
        if any(x.casefold() in {'$recycle.bin','system volume information','.pcspace-quarantine'} for x in p.parts):
            return '운영체제/이전 격리 저장소'
        return None

    def deletion_reason(self,p,recursive=False):
        reason = self.skip_directory(p)
        if reason:
            return reason
        if p in self.roots or str(p) == p.anchor or p == Path.home():
            return '드라이브·허용 루트·사용자 홈 자체는 삭제할 수 없습니다.'
        if p.name.casefold() in {'pagefile.sys','hiberfil.sys','swapfile.sys','ntuser.dat','ntuser.dat.log1','ntuser.dat.log2'}:
            return '운영체제에서 관리하는 파일'
        if recursive and any(inside(r,p) for r in self.hard+self.clouds):
            return '선택 폴더 안에 시스템·인증정보·사용자 지정 보호 경로가 있습니다.'
        return None

    def mutable(self,raw,expected=None):
        p=self.allowed(raw)
        s=unchanged(p,expected) if expected else snapshot(p)
        if s['attrs'] & (REPARSE|CLOUD|SYSTEM) or stat.S_ISLNK(s['mode']):
            raise PolicyError('시스템·링크·클라우드 속성 항목입니다.')
        if reason:=self.deletion_reason(p,stat.S_ISDIR(s['mode'])):
            raise PolicyError(reason)
        return p

    def protect(self,raw):
        p=self.allowed(raw)
        if str(p) not in self.data['protected_paths']:
            self.data['protected_paths'].append(str(p));self.save();self.reload()


def folder_hint(p: Path) -> tuple[str,str]:
    parts={v.casefold() for v in p.parts}
    if any(x.startswith('canonicalgrouplimited.ubuntu') for x in parts):
        return 'wsl','WSL Ubuntu 가상디스크/배포 데이터: 일반 찌꺼기가 아님 · WSL에서 용량을 관리'
    if {'appdata','local','packages'} <= parts:
        return 'appdata','Microsoft Store 앱 데이터: 앱/배포판 사용 여부를 확인'
    if parts & {'node_modules','.venv','venv','__pycache__','.pytest_cache','.mypy_cache','build','dist','.cache','cache','caches'}:
        return 'generated','캐시·빌드·의존성: 사용 중인지, 재생성 가능한지 확인'
    if parts & {'backup','backups','백업','포맷 백업'} or any('백업' in x for x in parts):
        return 'archive','보관·백업: 필요한 원본/다른 보관본인지 확인'
    if parts & {'workspace','workspaces','프로젝트','.git','mcp'}:
        return 'project','작업 프로젝트: 경로를 사용하는 프로그램에 영향'
    return 'normal','용량 기준 탐색 · 불필요 여부는 직접 판단'


def candidate_bytes(name: str,size: int,mtime: float,generated: bool,now: float) -> int:
    # Cheap hint only. No path stat, hashes, allocation query or database call per file.
    ext=os.path.splitext(name)[1].lower()
    age=(now-mtime)/86400
    return size if (generated or (ext in {'.tmp','.temp','.log','.crdownload','.partial'} and age>=7)
                    or (ext in INSTALL_EXTS and age>=90)) else 0
