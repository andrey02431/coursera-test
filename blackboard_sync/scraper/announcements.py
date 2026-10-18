"""Announcements via the real API, verified against a live response body:

    GET /learn/api/v1/courses/{courseId}/announcements
        ?limit=100&sort=startDateRestriction(desc)

Each result's body.rawText is the full announcement HTML (no truncation,
unlike the DOM list view's CSS-clamped preview this used to scrape).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from playwright.sync_api import Page

from ..config import Config
from ..storage import Manifest, safe_name, unique_path, write_text
from .api import build_url, paginated_results
from .courses import Course

logger = logging.getLogger(__name__)


def sync_announcements(page: Page, course: Course, course_dir: Path, config: Config, manifest: Manifest, debug_dir: Optional[Path]) -> int:
    url = build_url(
        config.base_url,
        f"/learn/api/v1/courses/{course.course_id}/announcements",
        limit=100,
        sort="startDateRestriction(desc)",
    )
    results = paginated_results(page, config, url)

    target_dir = course_dir / "announcements"
    saved = 0

    for item in results:
        item_id = item.get("id")
        if not item_id:
            continue

        title = item.get("title") or "untitled announcement"
        body_html = (item.get("body") or {}).get("rawText") or ""
        created = item.get("createdDate") or item.get("startDateRestriction") or ""

        fingerprint = f"{item.get('modifiedDate')}:{len(body_html)}"
        if manifest.is_unchanged(item_id, fingerprint):
            continue

        date_prefix = created[:10] if created else "undated"
        dest = unique_path(target_dir, f"{date_prefix}__{safe_name(title)}.html")
        write_text(dest, body_html or title)
        manifest.record(item_id, str(dest), fingerprint)
        saved += 1

    if not results:
        logger.info("No announcements found for course %s.", course.course_id)

    return saved
