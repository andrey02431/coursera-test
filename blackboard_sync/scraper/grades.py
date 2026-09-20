from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from playwright.sync_api import Page

from ..config import Config
from ..storage import write_json
from .common import dump, goto
from .courses import Course

logger = logging.getLogger(__name__)


def sync_grades(page: Page, course: Course, course_dir: Path, config: Config, debug_dir: Optional[Path]) -> int:
    sel = config.selectors
    url = config.base_url + sel["grades_url_template"].format(course_id=course.course_id)
    goto(page, url, config.timeout_ms, config.request_delay_seconds)
    dump(page, debug_dir, f"{course.course_id}_grades")

    rows = []
    for el in page.query_selector_all(sel["grade_row"]):
        name_el = el.query_selector(sel["grade_name"])
        score_el = el.query_selector(sel["grade_score"])
        feedback_el = el.query_selector(sel["grade_feedback"])
        rows.append(
            {
                "name": name_el.inner_text().strip() if name_el else None,
                "score": score_el.inner_text().strip() if score_el else None,
                "feedback": feedback_el.inner_text().strip() if feedback_el else None,
            }
        )

    if not rows:
        logger.info("No grades found for course %s (or selectors need tuning).", course.course_id)
        return 0

    write_json(course_dir / "grades" / "grades.json", rows)
    return len(rows)
