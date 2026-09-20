"""Enumerate the courses the logged-in user is enrolled in."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from playwright.sync_api import Page

from ..config import Config
from .common import dump, extract_id, goto

logger = logging.getLogger(__name__)


@dataclass
class Course:
    course_id: str
    name: str
    url: str


def list_courses(page: Page, config: Config, debug_dir: Optional[Path]) -> list[Course]:
    sel = config.selectors
    url = config.base_url + sel["course_list_url_path"]
    goto(page, url, config.timeout_ms, config.request_delay_seconds, settle_selector=sel["course_tile"])
    dump(page, debug_dir, "course_list")

    courses: dict[str, Course] = {}
    for tile in page.query_selector_all(sel["course_tile"]):
        attr_value = tile.get_attribute(sel["course_id_attr"]) or ""
        course_id = extract_id(attr_value, sel["course_id_regex"])
        if not course_id:
            continue
        name_el = tile.query_selector(sel["course_name"]) or tile
        name = (name_el.inner_text() or course_id).strip()
        # Course tiles use a JS click handler rather than a real href (Blackboard's
        # Angular-based course list), so we construct the Ultra outline URL
        # ourselves from the extracted ID rather than reading it off the tile.
        full_url = config.base_url + sel["content_outline_url_template"].format(course_id=course_id)
        courses[course_id] = Course(course_id=course_id, name=name, url=full_url)

    result = list(courses.values())
    if config.course_filter:
        result = [c for c in result if c.course_id in config.course_filter]

    if not result:
        logger.warning(
            "No courses found. This almost always means config/selectors.yaml "
            "needs tuning for Southampton's Blackboard theme - re-run with "
            "--debug-dump and inspect debug/course_list.html."
        )
    return result
