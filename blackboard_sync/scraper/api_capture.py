"""One-off diagnostic: record the real JSON API calls Blackboard Ultra's own
frontend makes while loading a page, using the session we already have
(the same one-time interactive login + 2FA, no new auth mechanism).

This exists because there's no realistic path to Blackboard's officially
documented REST API for a student account (it requires an institution
admin to register an OAuth integration), but the Ultra web app itself is
just calling same-origin, cookie-authenticated JSON endpoints to render
every page we've been scraping. Capturing those real calls - instead of
guessing endpoint shapes - is what the API-based rewrite of the scraper
gets built against.

The dumped JSON files include whatever Blackboard returns, which may
include grades, names and other personal data - handle debug/api/ like any
other debug dump (it's gitignored; don't share it outside this session).
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Optional

from playwright.sync_api import Page, Response

logger = logging.getLogger(__name__)


def _looks_like_api(response: Response) -> bool:
    url = response.url
    if "/api/" not in url:
        return False
    content_type = response.headers.get("content-type", "")
    return "json" in content_type.lower()


def capture_during(page: Page, out_dir: Path, label: str) -> dict:
    """Attach a response listener to ``page`` that saves every JSON API
    call observed to ``out_dir`` as ``<label>_NNN.json``, for as long as the
    listener stays attached (caller navigates/waits, then reads
    ``counter["n"]`` from the returned dict - capture happens
    asynchronously as responses arrive, so the count isn't known until
    after navigation/waiting is done).

    Playwright's Python sync API can invoke this callback from more than
    one thread for overlapping responses - confirmed on a live run, where
    "23 captured" left only 9 files on disk with gaps in the numbering,
    meaning concurrent calls read the same counter value and silently
    clobbered each other's file. The lock makes the read-increment-assign
    atomic so every response gets a genuinely unique filename; the slower
    body-fetch/write after that can still happen in any order safely, since
    each has already claimed a distinct number.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    counter = {"n": 0}
    lock = threading.Lock()

    def on_response(response: Response) -> None:
        try:
            if not _looks_like_api(response) or response.status >= 400:
                return
            with lock:
                counter["n"] += 1
                n = counter["n"]
            try:
                body = response.json()
            except Exception:
                body = None
            request = response.request
            record = {
                "method": request.method,
                "url": response.url,
                "status": response.status,
                "request_headers": dict(request.headers),
                "response_headers": dict(response.headers),
                "body": body,
            }
            path = out_dir / f"{label}_{n:03d}.json"
            path.write_text(json.dumps(record, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
        except Exception:
            logger.exception("Failed to capture API response for %s", response.url)

    page.on("response", on_response)
    return counter


def log_all_requests(page: Page, out_path: Path) -> list[str]:
    """Attach a listener that appends one line per request/response pair to
    ``out_path`` (method, url, status, content-type, timing) - everything,
    not just things that look like a JSON API. Diagnostic for "did this
    page even issue the request I'm expecting, and did it succeed, fail, or
    never come back" - which capture_during's filtered JSON-only view can't
    answer by itself (not every endpoint is under /api/ with a json
    content-type, e.g. the older Angular course-list page).

    Returns the same list object that keeps getting appended to, so the
    caller can inspect it directly without re-reading the file.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []

    def on_response(response: Response) -> None:
        try:
            request = response.request
            content_type = response.headers.get("content-type", "")
            line = f"{response.status}\t{request.method}\t{content_type}\t{response.url}"
        except Exception:
            line = f"ERROR capturing response for {getattr(response, 'url', '?')}"
        lines.append(line)
        try:
            out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except Exception:
            logger.exception("Failed to write request log to %s", out_path)

    def on_request_failed(request) -> None:
        line = f"FAILED\t{request.method}\t-\t{request.url}\t({request.failure})"
        lines.append(line)
        try:
            out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except Exception:
            logger.exception("Failed to write request log to %s", out_path)

    page.on("response", on_response)
    page.on("requestfailed", on_request_failed)
    return lines
