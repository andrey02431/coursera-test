"""Course content via the real API for discovery - a recursive walk of

    GET /learn/api/v1/courses/{courseId}/contents/{parentId}/children
        ?@view=Summary&limit=200

starting at the virtual parent id "ROOT" - instead of rendering/clicking
through the outline page. Verified against a live response body; see
docs/blackboard-api-recon-map.md for the full shape and what's still
unconfirmed (notably: no content-tree item of an actual file/reading has
been inspected yet, only folders and discussion links, so the file-vs-page
distinction below is still made the old way).

File downloads still go through the one proven mechanism found so far (no
API equivalent located yet): each leaf item's own Ultra detail page embeds
the real file URL in a hidden, non-clickable
<a data-ally-file-preview-url="https://.../bbcswebdav/...">, fetched
directly via context.request rather than simulating a click.

The item's own body.webLocation looked promising (present and
type-agnostic on every content-tree item seen) but turned out NOT to be
safely navigable as a direct top-level page - confirmed on a live run,
where visiting it landed on a plain "The specified resource was not found
or you do not have permission to access it" page (plausibly meant to be
loaded inside an iframe, not top-level). The URL is instead built per
contentHandler, same as the original DOM-based version used: the
Ultra document-view pattern for ordinary content, the discussion-view
pattern for forum links, and LTI tool-launch items (contentHandler
starting with "resource/x-bb-bltiplacement", e.g. a Teams meeting link)
are skipped outright - there's no document to fetch for those.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from playwright.sync_api import Page

from ..config import Config
from ..storage import Manifest, safe_name, unique_path, write_json, write_text
from .api import build_url, paginated_results
from .common import dump, goto, is_navigable
from .courses import Course

logger = logging.getLogger(__name__)


@dataclass
class ContentItem:
    item_id: str
    title: str
    path_parts: list[str]
    url: Optional[str]  # None for content types with nothing fetchable (e.g. an LTI tool launch)


def _is_folder(item: dict) -> bool:
    handler = item.get("contentHandler", "")
    detail = (item.get("contentDetail") or {}).get(handler) or {}
    return bool(detail.get("isFolder"))


def _item_url(base_url: str, course_id: str, content_id: str, content_handler: str) -> Optional[str]:
    if content_handler.startswith("resource/x-bb-bltiplacement"):
        return None  # external tool launch (e.g. a Teams meeting link) - nothing to fetch
    if content_handler == "resource/x-bb-forumlink":
        return f"{base_url}/ultra/courses/{course_id}/discussion/{content_id}?view=discussions"
    return f"{base_url}/ultra/courses/{course_id}/document/{content_id}?view=content&state=view"


def discover_items(page: Page, config: Config, course_id: str, root: str = "ROOT") -> list[ContentItem]:
    """Walk the contents tree starting at ``root`` - "ROOT" for the normal
    course outline, or "INTERACTIVE" for the discussions/engagement hub's
    virtual grouping of forum-link items (same tree shape either way, see
    discussions.py).
    """
    items: list[ContentItem] = []

    def walk(parent_id: str, path_parts: list[str]) -> None:
        url = build_url(
            config.base_url,
            f"/learn/api/v1/courses/{course_id}/contents/{parent_id}/children",
            {"@view": "Summary"},
            limit=200,
        )
        for child in paginated_results(page, config, url):
            content_id = child.get("id")
            title = child.get("title") or "untitled"
            if not content_id:
                continue

            if _is_folder(child):
                walk(content_id, path_parts + [title])
                continue

            item_url = _item_url(config.base_url, course_id, content_id, child.get("contentHandler", ""))
            items.append(ContentItem(item_id=content_id, title=title, path_parts=path_parts, url=item_url))

    walk(root, [])

    if not items:
        logger.warning("No content items found for course %s via the contents API (root=%s).", course_id, root)
    return items


def sync_content(page: Page, course: Course, course_dir: Path, config: Config, manifest: Manifest, debug_dir: Optional[Path]) -> int:
    sel = config.selectors
    items = discover_items(page, config, course.course_id)
    saved = 0

    # Verified against a real document detail page - see module docstring.
    file_link_selector = sel.get("content_detail_file_link", "a[data-ally-file-preview-url]")
    file_url_attr = sel.get("content_detail_file_url_attr", "data-ally-file-preview-url")
    file_label_selector = sel.get("content_detail_file_label", "[aria-label^='Preview File ']")
    body_selector = sel.get("content_detail_body", "main")

    for item in items:
        target_dir = course_dir / "content"
        for part in item.path_parts:
            target_dir = target_dir / safe_name(part)

        if not is_navigable(item.url):
            continue

        fingerprint = f"{item.url}:{item.title}"
        if manifest.is_unchanged(item.item_id, fingerprint):
            continue

        goto(page, item.url, config.timeout_ms, config.request_delay_seconds)
        dump(page, debug_dir, f"{course.course_id}_item_{item.item_id}")

        if config.content.files:
            file_link = page.query_selector(file_link_selector)
            if file_link is not None:
                file_url = file_link.get_attribute(file_url_attr)
                if file_url:
                    try:
                        response = page.context.request.get(file_url, timeout=config.timeout_ms)
                        if response.ok:
                            label_el = page.query_selector(file_label_selector)
                            label = label_el.get_attribute("aria-label") if label_el else None
                            filename = None
                            if label and label.lower().startswith("preview file "):
                                filename = label[len("preview file "):].strip()
                            dest = unique_path(target_dir, safe_name(filename) if filename else safe_name(item.title))
                            dest.write_bytes(response.body())
                            manifest.record(item.item_id, str(dest), fingerprint)
                            saved += 1
                            logger.info("Downloaded: %s", dest)
                            continue
                        logger.warning(
                            "Download request for %r returned HTTP %s", item.title, response.status
                        )
                    except Exception:
                        logger.exception("Failed to download item %r in course %s", item.title, course.course_id)

        if not config.content.pages:
            continue

        body_el = page.query_selector(body_selector)
        body_html = body_el.inner_html() if body_el else ""
        if "specified resource was not found" in body_html.lower():
            logger.warning(
                "Item %r (%s) in course %s landed on a Blackboard error page - "
                "skipping rather than saving it as content.",
                item.title, item.item_id, course.course_id,
            )
            continue
        dest = unique_path(target_dir, safe_name(item.title) + ".html")
        write_text(dest, body_html or item.title)
        write_json(
            dest.with_suffix(".meta.json"),
            {"title": item.title, "path": item.path_parts, "href": item.url, "course_id": course.course_id},
        )
        manifest.record(item.item_id, str(dest), fingerprint)
        saved += 1

    return saved
