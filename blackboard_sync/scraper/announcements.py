from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from playwright.sync_api import Page

from ..config import Config
from ..storage import Manifest, safe_name, unique_path, write_text
from .common import dump, goto
from .courses import Course

logger = logging.getLogger(__name__)


def sync_announcements(page: Page, course: Course, course_dir: Path, config: Config, manifest: Manifest, debug_dir: Optional[Path]) -> int:
    sel = config.selectors
    url = config.base_url + sel["announcements_url_template"].format(course_id=course.course_id)
    goto(page, url, config.timeout_ms, config.request_delay_seconds, settle_selector=sel["announcement_item"])
    dump(page, debug_dir, f"{course.course_id}_announcements")

    target_dir = course_dir / "announcements"
    saved = 0
    rows = page.query_selector_all(sel["announcement_item"])

    for el in rows:
        title_el = el.query_selector(sel["announcement_title"])
        body_el = el.query_selector(sel["announcement_body"])
        date_el = el.query_selector(sel["announcement_date"])

        title = (title_el.inner_text().strip() if title_el else "untitled announcement")
        body = body_el.inner_html() if body_el else ""
        date_text = (date_el.inner_text().strip() if date_el else "")

        item_id = f"announcement:{date_text}:{title}"
        fingerprint = f"{len(body)}:{title}"
        if manifest.is_unchanged(item_id, fingerprint):
            continue

        date_prefix = safe_name(date_text)[:10] or "undated"
        filename = f"{date_prefix}__{safe_name(title)}.html"
        dest = unique_path(target_dir, filename)
        write_text(dest, body or title)
        manifest.record(item_id, str(dest), fingerprint)
        saved += 1

    if not rows:
        logger.info("No announcements found for course %s (or selectors need tuning).", course.course_id)

    return saved
