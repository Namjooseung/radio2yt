"""사용자 데이터: 작업 기록, 직접 추가한 썸네일, 마지막 선택값.

위치: %APPDATA%\\SoneFM 유튜브 편집기\\ (설치 폴더가 아니라 사용자 폴더라 관리자 권한이 필요 없다)
"""
from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from pathlib import Path

from .theme import assets_dir

APP_NAME = "SoneFM 유튜브 편집기"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def data_dir() -> Path:
    base = Path(os.environ.get("APPDATA") or Path.home())
    d = base / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def default_save_dir() -> Path:
    return Path.home() / "Documents" / "SoneFM" / "유튜브"


# ── 설정 ──
def _settings_path() -> Path:
    return data_dir() / "settings.json"


def load_settings() -> dict:
    try:
        return json.loads(_settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_setting(key: str, value) -> None:
    s = load_settings()
    s[key] = value
    _settings_path().write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")


# ── 썸네일 ──
def builtin_thumb_dir() -> Path:
    return assets_dir() / "thumbnails"


def user_thumb_dir() -> Path:
    d = data_dir() / "thumbnails"
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_thumbnails() -> list[dict]:
    """[{path, name, builtin}] 기본 썸네일 먼저, 그다음 직접 추가한 것(최근 추가 순)."""
    out = []
    for d, builtin in ((builtin_thumb_dir(), True), (user_thumb_dir(), False)):
        if not d.exists():
            continue
        files = [p for p in d.iterdir() if p.suffix.lower() in IMAGE_EXTS]
        files.sort(key=(lambda p: p.name) if builtin else (lambda p: -p.stat().st_mtime))
        out += [{"path": str(p), "name": p.stem, "builtin": builtin} for p in files]
    return out


def add_thumbnail(src: str) -> str:
    src_p = Path(src)
    dst = user_thumb_dir() / src_p.name
    if dst.exists():
        dst = user_thumb_dir() / f"{src_p.stem}_{uuid.uuid4().hex[:6]}{src_p.suffix}"
    shutil.copy2(src_p, dst)
    os.utime(dst, None)
    return str(dst)


def remove_thumbnail(path: str) -> None:
    p = Path(path)
    if p.parent == user_thumb_dir():
        p.unlink(missing_ok=True)


# ── 작업 기록 ──
def _history_path() -> Path:
    return data_dir() / "history.json"


def load_history() -> list[dict]:
    try:
        return json.loads(_history_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def add_history(entry: dict) -> None:
    h = [e for e in load_history() if e.get("output") != entry.get("output")]
    entry = {**entry, "time": time.time()}
    h.insert(0, entry)
    _history_path().write_text(json.dumps(h[:200], ensure_ascii=False, indent=2), encoding="utf-8")
