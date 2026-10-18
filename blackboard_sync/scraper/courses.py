"""Enumerate the courses the logged-in user is enrolled in.

Calls Blackboard's real internal memberships API directly instead of
rendering/scraping the course list page - captured from a live session via
`discover-api`:

    GET /learn/api/v1/users/{userId}/memberships
        ?expand=course.effectiveAvailability,course.permissions,courseRole
        &includeCount=true&limit=10000

Authenticated by the same session cookies as everything else (no OAuth, no
extra login step). This replaces every DOM-scraping concern the old
course-list approach had - Angular skeleton-loading races, selector drift,
course IDs hidden in an `id` attribute instead of a real href - with one
fast, complete JSON response. It also surfaces courses the DOM-based course
list sometimes missed entirely (confirmed on a live account: a Classic/
Original-view course was present in this API response but never appeared
in the rendered course list in time).

Each membership's `course.ultraStatus` is "ULTRA" or "CLASSIC". Only Ultra
courses are supported by the rest of this scraper (content/announcements/
grades/discussions all assume Ultra's URL shapes); Classic ones are
reported with ``is_ultra=False`` so callers can skip them with a clear
reason instead of the old behaviour of just timing out repeatedly trying
to scrape pages that were never going to match.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from playwright.sync_api import Page

from ..config import Config
from ..storage import write_json
from .api import build_url, current_user_id, get_json

logger = logging.getLogger(__name__)


@dataclass
class Course:
    course_id: str
    name: str
    url: str
    is_ultra: bool
    is_closed: bool


def list_courses(page: Page, config: Config, debug_dir: Optional[Path]) -> list[Course]:
    user_id = current_user_id(page, config)
    if not user_id:
        return []

    url = build_url(
        config.base_url,
        f"/learn/api/v1/users/{user_id}/memberships",
        expand="course.effectiveAvailability,course.permissions,courseRole",
        includeCount="true",
        limit=10000,
    )
    body = get_json(page, config, url)
    if body is None:
        return []

    if debug_dir is not None:
        write_json(debug_dir / "course_list_api_response.json", body)

    courses: dict[str, Course] = {}
    for membership in body.get("results", []):
        c = membership.get("course") or {}
        course_id = c.get("id")
        if not course_id:
            continue

        is_ultra = c.get("ultraStatus") == "ULTRA"
        if is_ultra:
            course_url = c.get("externalAccessUrl") or f"{config.base_url}/ultra/courses/{course_id}/outline"
        else:
            home_page = c.get("homePageUrl") or f"/webapps/blackboard/execute/courseMain?course_id={course_id}"
            course_url = config.base_url + home_page

        courses[course_id] = Course(
            course_id=course_id,
            name=c.get("displayName") or c.get("name") or course_id,
            url=course_url,
            is_ultra=is_ultra,
            is_closed=bool(c.get("isClosed")),
        )

    result = list(courses.values())
    if config.course_filter:
        result = [c for c in result if c.course_id in config.course_filter]

    if not result:
        logger.warning("No courses found in the memberships API response.")
    return result
