"""Verified against a real Southampton grades page: each row is
<tr data-grade-id="..."> with per-column cells identified by
aria-describedby pointing at a stable header id
(course-student-grades-header-<itemName|dueDate|status|grade|results>).
"""

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


def _cell_text(el, selector: Optional[str]) -> Optional[str]:
    if not selector:
        return None
    cell = el.query_selector(selector)
    return cell.inner_text().strip() if cell else None


def sync_grades(page: Page, course: Course, course_dir: Path, config: Config, debug_dir: Optional[Path]) -> int:
    sel = config.selectors
    url = config.base_url + sel["grades_url_template"].format(course_id=course.course_id)
    goto(page, url, config.timeout_ms, config.request_delay_seconds, settle_selector=sel["grade_row"])
    dump(page, debug_dir, f"{course.course_id}_grades")

    rows = []
    for el in page.query_selector_all(sel["grade_row"]):
        rows.append(
            {
                "name": _cell_text(el, sel.get("grade_name")),
                "due_date": _cell_text(el, sel.get("grade_due")),
                "status": _cell_text(el, sel.get("grade_status")),
                "grade": _cell_text(el, sel.get("grade_score")),
                "results": _cell_text(el, sel.get("grade_results")),
            }
        )

    if not rows:
        logger.info("No grades found for course %s (or selectors need tuning).", course.course_id)
        return 0

    write_json(course_dir / "grades" / "grades.json", rows)
    return len(rows)
