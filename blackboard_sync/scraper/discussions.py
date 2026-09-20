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


def sync_discussions(page: Page, course: Course, course_dir: Path, config: Config, manifest: Manifest, debug_dir: Optional[Path]) -> int:
    sel = config.selectors
    url = config.base_url + sel["discussions_url_template"].format(course_id=course.course_id)
    goto(page, url, config.timeout_ms, config.request_delay_seconds, settle_selector=sel["discussion_forum_link"])
    dump(page, debug_dir, f"{course.course_id}_discussions")

    saved = 0
    forum_links = page.query_selector_all(sel["discussion_forum_link"])
    forum_urls = []
    for link in forum_links:
        href = link.get_attribute("href") or ""
        forum_name = (link.inner_text() or "forum").strip()
        forum_urls.append((forum_name, href if href.startswith("http") else config.base_url + href))

    for forum_name, forum_url in forum_urls:
        goto(page, forum_url, config.timeout_ms, config.request_delay_seconds, settle_selector=sel["discussion_thread_link"])
        dump(page, debug_dir, f"{course.course_id}_discussion_{safe_name(forum_name)}")

        thread_links = page.query_selector_all(sel["discussion_thread_link"])
        thread_urls = []
        for link in thread_links:
            href = link.get_attribute("href") or ""
            thread_title = (link.inner_text() or "thread").strip()
            thread_urls.append((thread_title, href if href.startswith("http") else config.base_url + href))

        for thread_title, thread_url in thread_urls:
            item_id = f"discussion:{forum_name}:{thread_title}"
            goto(page, thread_url, config.timeout_ms, config.request_delay_seconds, settle_selector=sel["discussion_thread_body"])
            body_el = page.query_selector(sel["discussion_thread_body"])
            body = body_el.inner_html() if body_el else ""
            fingerprint = f"{len(body)}"
            if manifest.is_unchanged(item_id, fingerprint):
                continue

            dest = unique_path(course_dir / "discussions" / safe_name(forum_name), safe_name(thread_title) + ".html")
            write_text(dest, body or thread_title)
            manifest.record(item_id, str(dest), fingerprint)
            saved += 1

    if not saved:
        logger.info("No discussion threads found for course %s (or selectors need tuning).", course.course_id)

    return saved
