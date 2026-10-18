from __future__ import annotations

import argparse
import logging
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from .browser import Session, SessionExpired, interactive_login, require_logged_in
from .config import Config
from .scraper.announcements import sync_announcements
from .scraper.api_capture import capture_during, log_all_requests
from .scraper.common import goto
from .scraper.content import sync_content
from .scraper.courses import list_courses
from .scraper.discussions import sync_discussions
from .scraper.grades import sync_grades
from .storage import Manifest, course_dir, write_json


def _setup_logging(config: Config) -> None:
    config.log_dir.mkdir(parents=True, exist_ok=True)
    log_file = config.log_dir / f"sync-{datetime.now().strftime('%Y%m%dT%H%M%S')}.log"
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(log_file, encoding="utf-8")],
    )


def cmd_login(args: argparse.Namespace) -> int:
    config = Config.load()
    ok = interactive_login(
        config.profile_dir, config.base_url, config.selectors["login_url_markers"], config.timeout_ms
    )
    return 0 if ok else 1


def cmd_status(args: argparse.Namespace) -> int:
    config = Config.load()
    with Session(config.profile_dir, headless=config.headless) as session:
        try:
            require_logged_in(session, config.base_url, config.selectors["login_url_markers"], config.timeout_ms)
        except SessionExpired as exc:
            print(exc)
            return 1
    print("Session is valid.")
    return 0


def cmd_discover(args: argparse.Namespace) -> int:
    config = Config.load()
    _setup_logging(config)
    debug_dir = config.debug_dir if args.debug_dump else None

    with Session(config.profile_dir, headless=config.headless) as session:
        require_logged_in(session, config.base_url, config.selectors["login_url_markers"], config.timeout_ms)
        page = session.new_page()
        courses = list_courses(page, config, debug_dir)
        print(f"Found {len(courses)} course(s):")
        for course in courses:
            tags = []
            if not course.is_ultra:
                tags.append("Classic/Original - not synced")
            if course.is_closed:
                tags.append("closed")
            suffix = f"  [{', '.join(tags)}]" if tags else ""
            print(f"  {course.course_id}\t{course.name}{suffix}")
        page.close()
    return 0


def cmd_discover_api(args: argparse.Namespace) -> int:
    config = Config.load()
    _setup_logging(config)
    out_dir = config.debug_dir / "api"
    # Start clean: capture_during's per-call counter restarts at 1 each run,
    # so leftover files from a previous run (which may have captured a
    # different number/order of calls) would otherwise mix with this run's
    # output under the same numbered filenames - confirmed happening on a
    # live run, where a response the request log showed had succeeded
    # wasn't actually among the files on disk afterwards.
    if out_dir.exists():
        shutil.rmtree(out_dir)

    with Session(config.profile_dir, headless=config.headless) as session:
        try:
            require_logged_in(session, config.base_url, config.selectors["login_url_markers"], config.timeout_ms)
        except SessionExpired as exc:
            print(exc)
            return 1

        page = session.new_page()
        counter = capture_during(page, out_dir, "course_list")
        request_log_path = config.debug_dir / "course_list_requests.log"
        log_all_requests(page, request_log_path)
        courses = list_courses(page, config, config.debug_dir)
        page.close()
        print(f"  course_list: {counter['n']} API call(s) captured")
        if not courses:
            print(
                f"No courses found - can't pick one to capture against. See "
                f"{config.debug_dir / 'course_list.html'} / .png, whatever "
                f"landed in {out_dir}, and the full request log at "
                f"{request_log_path} (every request/response the page made, "
                f"not just ones that looked like a JSON API)."
            )
            return 1

        course = courses[0]
        if args.course:
            match = next((c for c in courses if c.course_id == args.course), None)
            if match is None:
                print(f"Course {args.course!r} not found. Known IDs: {[c.course_id for c in courses]}")
                return 1
            course = match

        print(f"Capturing real API calls against course: {course.name} ({course.course_id})")
        sel = config.selectors
        sections = {
            "course_list": config.base_url + sel["course_list_url_path"],
            "outline": config.base_url + sel["content_outline_url_template"].format(course_id=course.course_id),
            "announcements": config.base_url + sel["announcements_url_template"].format(course_id=course.course_id),
            "grades": config.base_url + sel["grades_url_template"].format(course_id=course.course_id),
            "engagement": config.base_url + sel["discussions_url_template"].format(course_id=course.course_id),
        }

        total = 0
        for label, url in sections.items():
            section_page = session.new_page()
            counter = capture_during(section_page, out_dir, label)
            goto(section_page, url, config.timeout_ms, config.request_delay_seconds)
            section_page.wait_for_timeout(4000)  # let trailing XHRs finish arriving
            section_page.close()
            print(f"  {label}: {counter['n']} API call(s) captured")
            total += counter["n"]

    print(f"\nDone. {total} API call(s) saved under {out_dir}")
    print(
        "These files may contain grades/personal data like any other debug "
        "dump - keep them local, don't publish them. Share the relevant "
        "ones here so the scraper can be rebuilt against the real API shapes."
    )
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    config = Config.load()
    if args.course:
        config.course_filter = [args.course]
    _setup_logging(config)
    logger = logging.getLogger("blackboard_sync.sync")
    debug_dir = config.debug_dir if args.debug_dump else None

    with Session(config.profile_dir, headless=config.headless) as session:
        try:
            require_logged_in(session, config.base_url, config.selectors["login_url_markers"], config.timeout_ms)
        except SessionExpired as exc:
            logger.error(str(exc))
            return 1

        page = session.new_page()
        courses = list_courses(page, config, debug_dir)
        if not courses:
            logger.warning("No courses to sync.")
            return 0

        totals = {"files": 0, "announcements": 0, "grades": 0, "discussions": 0}

        for course in courses:
            cdir = course_dir(config.output_dir, course.course_id, course.name)
            write_json(
                cdir / "course.meta.json",
                {"course_id": course.course_id, "name": course.name, "url": course.url, "is_ultra": course.is_ultra},
            )

            if not course.is_ultra:
                logger.info(
                    "Skipping %s (%s) - Original/Classic course view isn't supported yet, only Ultra.",
                    course.name, course.course_id,
                )
                continue

            logger.info("Syncing course: %s (%s)", course.name, course.course_id)
            manifest = Manifest(cdir / ".manifest.json")

            if config.content.files or config.content.pages:
                totals["files"] += sync_content(page, course, cdir, config, manifest, debug_dir)
                manifest.save()

            if config.content.announcements:
                totals["announcements"] += sync_announcements(page, course, cdir, config, manifest, debug_dir)
                manifest.save()

            if config.content.grades:
                totals["grades"] += sync_grades(page, course, cdir, config, debug_dir)

            if config.content.discussions:
                totals["discussions"] += sync_discussions(page, course, cdir, config, manifest, debug_dir)
                manifest.save()

        page.close()
        logger.info(
            "Sync complete. New/updated - files+pages: %d, announcements: %d, grades rows: %d, discussion threads: %d",
            totals["files"], totals["announcements"], totals["grades"], totals["discussions"],
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="blackboard_sync")
    sub = parser.add_subparsers(dest="command", required=True)

    p_login = sub.add_parser("login", help="Interactively log in (with 2FA) and save the session.")
    p_login.set_defaults(func=cmd_login)

    p_status = sub.add_parser("status", help="Check whether the saved session is still valid.")
    p_status.set_defaults(func=cmd_status)

    p_discover = sub.add_parser("discover", help="List courses/content without downloading anything.")
    p_discover.add_argument("--debug-dump", action="store_true", help="Save HTML/screenshots of every page visited.")
    p_discover.set_defaults(func=cmd_discover)

    p_api = sub.add_parser(
        "discover-api",
        help="Capture the real JSON API calls Blackboard's own frontend makes, for building an API-based scraper.",
    )
    p_api.add_argument("--course", help="Capture against this course ID instead of the first one found.")
    p_api.set_defaults(func=cmd_discover_api)

    p_sync = sub.add_parser("sync", help="Download new/changed content for all (or one) course.")
    p_sync.add_argument("--course", help="Only sync this course ID (as shown by `discover`).")
    p_sync.add_argument("--debug-dump", action="store_true", help="Save HTML/screenshots of every page visited.")
    p_sync.set_defaults(func=cmd_sync)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
