"""Walk a course's content outline (files, folders, and page text) and save
it into a folder structure mirroring Blackboard's own hierarchy.

Verified against a real Southampton Ultra course outline dump: each item is
a ``<div class="content-list-item" data-content-id="...">``. Folders
("Learning Modules") wrap a toggle button whose id is
``learning-module-title-<content-id>``; once expanded, their children appear
as further ``.content-list-item`` divs nested inside a
``#learning-module-contents-<content-id>`` container, which is how we
reconstruct the folder path for each leaf (see ``_ANCESTOR_PATH_JS``).

Leaf items link to their own Ultra detail page (e.g. a "document" viewer)
rather than exposing a direct file URL in the outline itself, so fetching a
file is a two-step process: follow the item's link, then look for an actual
download control on that detail page. What that control looks like hasn't
been verified against a real Southampton document page yet - if `sync`
reports 0 files despite finding content items, that's the next thing to fix
via a debug dump of one such detail page (config: content_detail_download_link).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from playwright.sync_api import Page

from ..config import Config
from ..storage import Manifest, safe_name, unique_path, write_json, write_text
from .common import dump, expand_all_folders, goto
from .courses import Course

logger = logging.getLogger(__name__)

_ANCESTOR_PATH_JS = """
el => {
    const parts = [];
    let node = el.parentElement;
    while (node) {
        if (node.id && node.id.indexOf('learning-module-contents-') === 0) {
            const suffix = node.id.slice('learning-module-contents-'.length);
            const titleEl = document.getElementById('learning-module-title-' + suffix);
            parts.unshift(titleEl ? titleEl.textContent.trim() : suffix);
        }
        node = node.parentElement;
    }
    return parts;
}
"""


@dataclass
class ContentItem:
    item_id: str
    title: str
    path_parts: list[str]
    href: Optional[str]


def discover_items(page: Page, course: Course, config: Config, debug_dir: Optional[Path]) -> list[ContentItem]:
    sel = config.selectors
    url = config.base_url + sel["content_outline_url_template"].format(course_id=course.course_id)
    goto(page, url, config.timeout_ms, config.request_delay_seconds, settle_selector=sel["content_item"])
    expand_all_folders(page, sel["content_folder_toggle"])
    dump(page, debug_dir, f"{course.course_id}_content_outline")

    id_attr = sel.get("content_item_id_attr", "data-content-id")
    link_selector = sel.get("content_item_link", "a[href]")

    out: list[ContentItem] = []
    for el in page.query_selector_all(sel["content_item"]):
        content_id = el.get_attribute(id_attr)
        if not content_id:
            continue

        # A folder ("Learning Module") is identified by owning a title
        # control with this exact id - checked precisely (not just "does
        # this element contain any expand button anywhere") because once
        # expanded, a folder's children live *inside* the same DOM subtree
        # and would otherwise be mistaken for the folder's own link/title.
        is_folder = el.query_selector(f'[id="learning-module-title-{content_id}"]') is not None
        if is_folder:
            continue

        link = el.query_selector(link_selector)
        title = ((link.inner_text() if link else el.inner_text()) or "").strip() or "untitled"
        href = link.get_attribute("href") if link else None

        path_parts = el.evaluate(_ANCESTOR_PATH_JS)
        out.append(ContentItem(item_id=content_id, title=title, path_parts=path_parts, href=href))

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
    saved = 0

    download_selector = sel.get("content_detail_download_link", "a[href*='bbcswebdav'], a[download]")
    body_selector = sel.get("content_detail_body", "main")

    for item in items:
        target_dir = course_dir / "content"
        for part in item.path_parts:
            target_dir = target_dir / safe_name(part)

        if not item.href:
            continue

        fingerprint = f"{item.href}:{item.title}"
        if manifest.is_unchanged(item.item_id, fingerprint):
            continue

        goto(page, item.href, config.timeout_ms, config.request_delay_seconds)
        dump(page, debug_dir, f"{course.course_id}_item_{item.item_id}")

        if config.content.files:
            download_link = page.query_selector(download_selector)
            if download_link is not None:
                try:
                    with page.expect_download(timeout=config.timeout_ms) as dl_info:
                        download_link.click()
                    download = dl_info.value
                    dest = unique_path(target_dir, download.suggested_filename or safe_name(item.title))
                    download.save_as(str(dest))
                    manifest.record(item.item_id, str(dest), fingerprint)
                    saved += 1
                    logger.info("Downloaded: %s", dest)
                    continue
                except Exception:
                    logger.exception("Failed to download item %r in course %s", item.title, course.course_id)

        if not config.content.pages:
            continue

        body_el = page.query_selector(body_selector)
        body_html = body_el.inner_html() if body_el else ""
        dest = unique_path(target_dir, safe_name(item.title) + ".html")
        write_text(dest, body_html or item.title)
        write_json(
            dest.with_suffix(".meta.json"),
            {"title": item.title, "path": item.path_parts, "href": item.href, "course_id": course.course_id},
        )
        manifest.record(item.item_id, str(dest), fingerprint)
        saved += 1

    return saved
