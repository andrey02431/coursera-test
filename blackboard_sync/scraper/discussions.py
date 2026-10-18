"""Discussion topics via the real API - discovery reuses content.py's exact
same contents-tree walker, just rooted at the virtual parent id
"INTERACTIVE" instead of "ROOT":

    GET /learn/api/v1/courses/{courseId}/contents/INTERACTIVE/children

Verified against a live response body: each result is a
contentHandler="resource/x-bb-forumlink" item, same shape as any other
content-tree item, with body.webLocation as a type-agnostic "open this"
URL - exactly like content.py's leaf items.

Each forum-link item also carries a contentDetailUrl pointing at
/learn/api/v1/courses/{courseId}/discussionboards/{conferenceId}/forums/{forumId}
- a real endpoint, but its response body hasn't been inspected yet (see
docs/blackboard-api-recon-map.md's "known unknowns"), so actual post
content still comes from visiting the topic's page and saving whatever its
main content region renders, same fallback content.py uses for an item
with no downloadable file.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from playwright.sync_api import Page

from ..config import Config
from ..storage import Manifest, safe_name, unique_path, write_text
from .common import dump, goto, is_navigable
from .content import discover_items
from .courses import Course

logger = logging.getLogger(__name__)


def sync_discussions(page: Page, course: Course, course_dir: Path, config: Config, manifest: Manifest, debug_dir: Optional[Path]) -> int:
    sel = config.selectors
    body_selector = sel.get("discussion_thread_body", sel.get("content_detail_body", "main"))

    topics = discover_items(page, config, course.course_id, root="INTERACTIVE")
    if not topics:
        return 0

    saved = 0
    for topic in topics:
        if not is_navigable(topic.url):
            continue

        item_id = f"discussion:{topic.item_id}"
        goto(page, topic.url, config.timeout_ms, config.request_delay_seconds)
        dump(page, debug_dir, f"{course.course_id}_discussion_{topic.item_id}")

        body_el = page.query_selector(body_selector)
        body_html = body_el.inner_html() if body_el else ""
        fingerprint = f"{len(body_html)}"
        if manifest.is_unchanged(item_id, fingerprint):
            continue

        path_parts = topic.path_parts
        dest_dir = course_dir / "discussions"
        for part in path_parts:
            dest_dir = dest_dir / safe_name(part)
        dest = unique_path(dest_dir, safe_name(topic.title) + ".html")
        write_text(dest, body_html or topic.title)
        manifest.record(item_id, str(dest), fingerprint)
        saved += 1

    if not saved:
        logger.info("No new/changed discussion topics for course %s.", course.course_id)

    return saved
