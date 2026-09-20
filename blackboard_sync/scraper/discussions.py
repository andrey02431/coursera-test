"""Course discussions live on Blackboard's "engagement" hub, not a
/discussions URL (the course nav's "Discussions" tab actually links to
.../engagement - verified against a real Southampton course). That page
turns out to reuse the exact same content-list-item component as the
content outline: each discussion topic is a
div.content-list-item[data-content-id] with a real <a href> straight to
.../discussion/<id>?view=discussions, so topic discovery reuses the
content_item/content_item_link selectors rather than separate ones.

What a topic page with actual posts looks like hasn't been verified yet -
the one seen during testing had none - so post-content extraction just
saves the page's main content region as a debug/iteration starting point
(content_detail_body, shared with content.py's fallback).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from playwright.sync_api import Page

from ..config import Config
from ..storage import Manifest, safe_name, unique_path, write_text
from .common import dump, goto, is_navigable
from .courses import Course

logger = logging.getLogger(__name__)


def sync_discussions(page: Page, course: Course, course_dir: Path, config: Config, manifest: Manifest, debug_dir: Optional[Path]) -> int:
    sel = config.selectors
    url = config.base_url + sel["discussions_url_template"].format(course_id=course.course_id)

    item_selector = sel.get("discussion_item", sel["content_item"])
    id_attr = sel.get("discussion_item_id_attr", sel.get("content_item_id_attr", "data-content-id"))
    link_selector = sel.get("discussion_item_link", sel.get("content_item_link", "a[href]"))
    body_selector = sel.get("discussion_thread_body", sel.get("content_detail_body", "main"))

    goto(page, url, config.timeout_ms, config.request_delay_seconds, settle_selector=item_selector)
    dump(page, debug_dir, f"{course.course_id}_discussions")

    topics: list[tuple[str, str, Optional[str]]] = []
    for el in page.query_selector_all(item_selector):
        content_id = el.get_attribute(id_attr)
        if not content_id:
            continue
        link = el.query_selector(link_selector)
        title = ((link.inner_text() if link else el.inner_text()) or "").strip() or "untitled"
        href = link.get_attribute("href") if link else None
        topics.append((content_id, title, href))

    if not topics:
        logger.warning(
            "No discussion topics found for course %s - selectors likely need "
            "tuning (see config/selectors.yaml).",
            course.course_id,
        )
        return 0

    saved = 0
    for content_id, title, href in topics:
        if not is_navigable(href):
            continue

        item_id = f"discussion:{content_id}"
        goto(page, href, config.timeout_ms, config.request_delay_seconds)
        dump(page, debug_dir, f"{course.course_id}_discussion_{content_id}")

        body_el = page.query_selector(body_selector)
        body_html = body_el.inner_html() if body_el else ""
        fingerprint = f"{len(body_html)}"
        if manifest.is_unchanged(item_id, fingerprint):
            continue

        dest = unique_path(course_dir / "discussions", safe_name(title) + ".html")
        write_text(dest, body_html or title)
        manifest.record(item_id, str(dest), fingerprint)
        saved += 1

    if not saved:
        logger.info("No new/changed discussion topics for course %s.", course.course_id)

    return saved
