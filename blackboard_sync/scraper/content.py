"""Walk a course's content outline (files, folders, and page text) and save
it into a folder structure mirroring Blackboard's own hierarchy.

Hierarchy reconstruction assumes the outline is rendered as an accessible
tree (``aria-level`` on each row, folders distinguished by ``aria-expanded``)
which is how Blackboard Ultra's outline is typically built. If Southampton's
theme differs, adjust ``content_item_level_attr`` in selectors.yaml, or - if
levels aren't exposed at all - every item will land flat under the course's
content/ root, which is a safe (if flatter-than-ideal) fallback rather than
a crash.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from playwright.sync_api import ElementHandle, Page

from ..config import Config
from ..storage import Manifest, safe_name, unique_path, write_json, write_text
from .common import dump, expand_all_folders, goto
from .courses import Course

logger = logging.getLogger(__name__)


@dataclass
class ContentItem:
    item_id: str
    title: str
    path_parts: list[str]
    has_download: bool


def _stable_id(el: ElementHandle, title: str, path_parts: list[str], id_attr: str) -> str:
    native_id = el.get_attribute(id_attr)
    if native_id:
        return native_id
    return "path:" + "/".join([*path_parts, title])


def discover_items(page: Page, course: Course, config: Config, debug_dir: Optional[Path]) -> list[tuple[ContentItem, ElementHandle]]:
    sel = config.selectors
    url = config.base_url + sel["content_outline_url_template"].format(course_id=course.course_id)
    goto(page, url, config.timeout_ms, config.request_delay_seconds)
    expand_all_folders(page, sel["content_folder_toggle"])
    dump(page, debug_dir, f"{course.course_id}_content_outline")

    level_attr = sel.get("content_item_level_attr", "aria-level")
    id_attr = sel.get("content_item_id_attr", "id")

    stack: list[tuple[int, str]] = []
    out: list[tuple[ContentItem, ElementHandle]] = []

    for el in page.query_selector_all(sel["content_item"]):
        title_el = el.query_selector(sel["content_item_title"]) or el
        title = (title_el.inner_text() or "").strip() or "untitled"

        level_raw = el.get_attribute(level_attr)
        level = int(level_raw) if level_raw and level_raw.isdigit() else 1
        is_folder = el.get_attribute("aria-expanded") is not None

        while stack and stack[-1][0] >= level:
            stack.pop()
        path_parts = [name for _, name in stack]

        if is_folder:
            stack.append((level, title))
            continue

        has_download = el.query_selector(sel["content_item_download_link"]) is not None
        item_id = _stable_id(el, title, path_parts, id_attr)
        out.append((ContentItem(item_id=item_id, title=title, path_parts=path_parts, has_download=has_download), el))

    if not out:
        logger.warning(
            "No content items found for course %s - selectors likely need "
            "tuning (see config/selectors.yaml).",
            course.course_id,
        )
    return out


def sync_content(page: Page, course: Course, course_dir: Path, config: Config, manifest: Manifest, debug_dir: Optional[Path]) -> int:
    sel = config.selectors
    items = discover_items(page, course, config, debug_dir)
    downloaded = 0

    for item, el in items:
        target_dir = course_dir / "content"
        for part in item.path_parts:
            target_dir = target_dir / safe_name(part)

        if item.has_download:
            fingerprint = f"file:{item.title}"
            if manifest.is_unchanged(item.item_id, fingerprint):
                continue
            link = el.query_selector(sel["content_item_download_link"])
            if link is None:
                continue
            try:
                with page.expect_download(timeout=config.timeout_ms) as dl_info:
                    link.click()
                download = dl_info.value
                dest = unique_path(target_dir, download.suggested_filename or safe_name(item.title))
                download.save_as(str(dest))
                manifest.record(item.item_id, str(dest), fingerprint)
                downloaded += 1
                logger.info("Downloaded: %s", dest)
            except Exception:
                logger.exception("Failed to download item %r in course %s", item.title, course.course_id)
            continue

        if not config.content.pages:
            continue

        try:
            body_html = el.inner_html()
        except Exception:
            body_html = ""
        fingerprint = f"page:{hash(body_html)}"
        if manifest.is_unchanged(item.item_id, fingerprint):
            continue

        dest = unique_path(target_dir, safe_name(item.title) + ".html")
        write_text(dest, body_html)
        write_json(
            dest.with_suffix(".meta.json"),
            {"title": item.title, "path": item.path_parts, "course_id": course.course_id},
        )
        manifest.record(item.item_id, str(dest), fingerprint)
        downloaded += 1

    return downloaded
