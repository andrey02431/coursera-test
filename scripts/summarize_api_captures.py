"""Summarize debug/api/*.json captures from `discover-api` into a compact,
deduped list of (method, path) endpoints - run after a capture that
produced too many files to review one by one.

Usage: python scripts/summarize_api_captures.py
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parent.parent
API_DIR = REPO_ROOT / "debug" / "api"


def main() -> int:
    files = sorted(API_DIR.glob("*.json"))
    if not files:
        print(f"No capture files found in {API_DIR}")
        return 1

    # (method, path) -> {"count": n, "example_url": str, "files": [...]}
    endpoints: dict[tuple[str, str], dict] = defaultdict(lambda: {"count": 0, "example_url": "", "files": []})

    for path in files:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        method = record.get("method", "?")
        url = record.get("url", "")
        split = urlsplit(url)
        key = (method, split.path)
        entry = endpoints[key]
        entry["count"] += 1
        if not entry["example_url"]:
            entry["example_url"] = url
        entry["files"].append(path.name)

    print(f"{len(files)} capture file(s) -> {len(endpoints)} unique (method, path) endpoint(s)\n")
    for (method, path_), entry in sorted(endpoints.items(), key=lambda kv: kv[0][1]):
        print(f"{entry['count']:>3}x  {method:<6} {path_}")
        print(f"        e.g. {entry['example_url']}")
        print(f"        e.g. file: debug/api/{entry['files'][0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
