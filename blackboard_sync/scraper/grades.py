"""Grades via the real API, verified against a live response body:

    GET /learn/api/v1/courses/{courseId}/gradebook/grades
        ?userId={userId}&limit=200&expand=column&includeNoGradeItems=true

expand=column embeds the full column definition (name, due date, points
possible) in each grade record, so a single call covers what the old DOM
scraper needed two sources for (the Marks page's name/status/score cells).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from playwright.sync_api import Page

from ..config import Config
from ..storage import write_json
from .api import build_url, current_user_id, paginated_results
from .courses import Course

logger = logging.getLogger(__name__)


def sync_grades(page: Page, course: Course, course_dir: Path, config: Config, debug_dir: Optional[Path]) -> int:
    user_id = current_user_id(page, config)
    if not user_id:
        logger.error("Could not resolve current user - skipping grades for course %s.", course.course_id)
        return 0

    url = build_url(
        config.base_url,
        f"/learn/api/v1/courses/{course.course_id}/gradebook/grades",
        userId=user_id,
        limit=200,
        expand="column",
        includeNoGradeItems="true",
    )
    results = paginated_results(page, config, url)

    rows = []
    for item in results:
        column = item.get("column") or {}
        display = item.get("displayGrade") or {}
        rows.append(
            {
                "name": column.get("effectiveColumnName") or column.get("columnName"),
                "due_date": column.get("dueDate"),
                "status": item.get("status"),
                "grade": display.get("grade"),
                "score": item.get("effectiveScore"),
                "points_possible": item.get("pointsPossible"),
            }
        )

    if not rows:
        logger.info("No grades found for course %s.", course.course_id)
        return 0

    write_json(course_dir / "grades" / "grades.json", rows)
    return len(rows)
