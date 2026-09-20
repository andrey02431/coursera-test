"""Filesystem layout, filename sanitization, and the incremental-sync manifest.

Kept free of any Playwright/network dependency so it can be unit tested
directly.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WHITESPACE = re.compile(r"\s+")


def safe_name(name: str, max_len: int = 150) -> str:
    """Turn an arbitrary Blackboard title into a safe filesystem entry name."""
    name = (name or "").strip()
    name = _INVALID_CHARS.sub("_", name)
    name = _WHITESPACE.sub(" ", name).strip()
    name = name.rstrip(" .")
    if not name:
        name = "untitled"
    return name[:max_len]


def course_dir(output_dir: Path, course_id: str, course_name: str) -> Path:
    d = output_dir / safe_name(f"{course_id} - {course_name}")
    d.mkdir(parents=True, exist_ok=True)
    return d


def unique_path(directory: Path, filename: str) -> Path:
    """Avoid clobbering an existing, differently-sourced file with the same name."""
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem, dot, ext = filename.partition(".")
    n = 2
    while True:
        candidate = directory / (f"{stem} ({n}){dot}{ext}" if dot else f"{stem} ({n})")
        if not candidate.exists():
            return candidate
        n += 1


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@dataclass
class ManifestEntry:
    item_id: str
    path: str
    fingerprint: str
    first_seen: str
    last_seen: str

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "fingerprint": self.fingerprint,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
        }


class Manifest:
    """Tracks which content items have already been synced for one course,
    so re-runs skip unchanged items instead of re-downloading everything.

    ``fingerprint`` is caller-defined - typically a Blackboard "last
    modified" string when available, falling back to a file size/hash.
    An item is considered unchanged if item_id AND fingerprint both match.
    """

    def __init__(self, path: Path):
        self.path = path
        if path.exists():
            self._data: dict[str, dict] = json.loads(path.read_text(encoding="utf-8"))
        else:
            self._data = {}

    def get(self, item_id: str) -> Optional[dict]:
        return self._data.get(item_id)

    def is_unchanged(self, item_id: str, fingerprint: str) -> bool:
        entry = self._data.get(item_id)
        return entry is not None and entry.get("fingerprint") == fingerprint

    def record(self, item_id: str, path: str, fingerprint: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        existing = self._data.get(item_id)
        first_seen = existing["first_seen"] if existing else now
        self._data[item_id] = ManifestEntry(
            item_id=item_id,
            path=path,
            fingerprint=fingerprint,
            first_seen=first_seen,
            last_seen=now,
        ).to_dict()

    def save(self) -> None:
        write_json(self.path, self._data)

    def __len__(self) -> int:
        return len(self._data)
