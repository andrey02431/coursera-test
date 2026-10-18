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
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    counter = {"n": 0}

    def on_response(response: Response) -> None:
        try:
            if not _looks_like_api(response) or response.status >= 400:
                return
            counter["n"] += 1
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
            path = out_dir / f"{label}_{counter['n']:03d}.json"
            path.write_text(json.dumps(record, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
        except Exception:
            logger.exception("Failed to capture API response for %s", response.url)

    page.on("response", on_response)
    return counter
