"""Shared helpers for the scraper submodules: polite navigation, and the
--debug-dump escape hatch used to tune config/selectors.yaml against the
real Southampton portal without needing code changes.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Optional

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

logger = logging.getLogger(__name__)

_COURSE_ID_RE = re.compile(r"/ultra/courses/([^/?#]+)")


def goto(page: Page, url: str, timeout_ms: int, delay_seconds: float, settle_selector: Optional[str] = None) -> None:
    """Navigate with a polite delay before the request, so a full sync
    doesn't hammer the server with back-to-back requests.

    Blackboard Ultra is a client-rendered SPA: the network can go idle
    (page loaded, initial API calls done) well before the actual content
    has finished rendering - it shows a spinner in between. If
    ``settle_selector`` is given, we wait for it to actually appear before
    moving on (falling back to a fixed grace period if it never shows, so a
    genuinely-empty page or a wrong selector doesn't hang forever). Without
    a selector, we just wait a fixed grace period.
    """
    time.sleep(delay_seconds)
    page.goto(url, wait_until="networkidle", timeout=timeout_ms)
    if settle_selector:
        try:
            page.wait_for_selector(settle_selector, timeout=timeout_ms, state="attached")
            return
        except PlaywrightTimeoutError:
            logger.warning(
                "Timed out waiting for %r to appear on %s - the page may still be "
                "showing a loading spinner, or the selector needs tuning. "
                "Continuing anyway so a debug dump can be captured.",
                settle_selector, url,
            )
    page.wait_for_timeout(2000)


def dump(page: Page, debug_dir: Optional[Path], name: str) -> None:
    """Save the current page's HTML + a screenshot to debug_dir, if enabled.

    This is the primary tool for fixing selectors that don't match
    Southampton's actual Blackboard theme: run any command with
    --debug-dump, then open debug/<name>.html / .png to see exactly what
    the scraper saw.
    """
    if debug_dir is None:
        return
    debug_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", name)[:120]
    try:
        (debug_dir / f"{safe}.html").write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(debug_dir / f"{safe}.png"), full_page=True)
        logger.info("Saved debug dump: %s.html / .png", safe)
    except Exception:
        logger.exception("Failed to write debug dump for %s", name)


def extract_course_id(href: str) -> Optional[str]:
    match = _COURSE_ID_RE.search(href)
    return match.group(1) if match else None


def expand_all_folders(page: Page, toggle_selector: str, max_rounds: int = 25) -> None:
    """Repeatedly click any collapsed-folder toggles until none remain (or
    we hit max_rounds, as a safety valve against an infinite loop if a
    selector is wrong and never disappears).
    """
    for _ in range(max_rounds):
        toggles = page.query_selector_all(toggle_selector)
        if not toggles:
            return
        clicked_any = False
        for toggle in toggles:
            try:
                if toggle.is_visible():
                    toggle.click(timeout=2000)
                    clicked_any = True
                    page.wait_for_timeout(300)
            except Exception:
                continue
        if not clicked_any:
            return
