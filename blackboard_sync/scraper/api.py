"""Shared helpers for talking to Blackboard's real internal JSON API
directly (same cookie-authenticated session as everything else, no OAuth).
Endpoint shapes here were captured live via `discover-api` and verified
against real response bodies - see docs/blackboard-api-notes.md.
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from urllib.parse import urlencode

from playwright.sync_api import Page

from ..config import Config

logger = logging.getLogger(__name__)


def get_json(page: Page, config: Config, url: str) -> Optional[dict]:
    response = page.context.request.get(url, timeout=config.timeout_ms)
    if not response.ok:
        logger.error("API request failed (HTTP %s): %s", response.status, url)
        return None
    return response.json()


def build_url(base_url: str, path: str, params: Optional[dict] = None, **kwargs: Any) -> str:
    """`params` is for query keys that aren't valid Python identifiers
    (Blackboard uses "@view=Summary" on content-tree calls); kwargs is the
    convenient form for everything else. Both merge into one query string.
    """
    query: dict[str, Any] = dict(params or {})
    query.update(kwargs)
    query = {k: v for k, v in query.items() if v is not None}
    return f"{base_url}{path}" + (f"?{urlencode(query)}" if query else "")


def paginated_results(page: Page, config: Config, url: str) -> list[dict]:
    """Follow `paging.nextPage` until exhausted, returning every `results`
    entry combined. Every list endpoint seen so far (announcements, grades,
    content children) shares this exact {results, paging, permissions}
    shape, with paging as {limit, count, offset, nextPage, previousPage}.
    """
    results: list[dict] = []
    next_url: Optional[str] = url
    while next_url:
        body = get_json(page, config, next_url)
        if body is None:
            break
        results.extend(body.get("results", []))
        next_page = (body.get("paging") or {}).get("nextPage") or ""
        next_url = config.base_url + next_page if next_page else None
    return results


def current_user_id(page: Page, config: Config) -> Optional[str]:
    body = get_json(page, config, f"{config.base_url}/learn/api/v1/users/me")
    return body.get("id") if body else None
