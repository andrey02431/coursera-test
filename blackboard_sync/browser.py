"""Persistent, cookie-reusing browser session.

The whole point of this module: log in once interactively (2FA included),
persist the authenticated profile to disk, and reuse it headlessly forever
after - until Blackboard/SSO expires the session, at which point we fail
loudly rather than silently doing nothing.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

from playwright.sync_api import BrowserContext, Playwright, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

logger = logging.getLogger(__name__)


class SessionExpired(RuntimeError):
    """Raised when the saved profile no longer has a valid Blackboard session."""


class Session:
    """Owns a Playwright instance + persistent browser context.

    Use as a context manager:

        with Session(profile_dir, headless=True) as session:
            page = session.new_page()
            ...
    """

    def __init__(self, profile_dir: Path, headless: bool):
        self.profile_dir = profile_dir
        self.headless = headless
        self._playwright: Playwright | None = None
        self.context: BrowserContext | None = None

    def __enter__(self) -> "Session":
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = sync_playwright().start()
        self.context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.profile_dir),
            headless=self.headless,
            viewport={"width": 1440, "height": 1000},
            accept_downloads=True,
        )
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.context is not None:
            self.context.close()
        if self._playwright is not None:
            self._playwright.stop()

    def new_page(self):
        assert self.context is not None
        return self.context.new_page()


def looks_like_login_page(url: str, login_url_markers: Iterable[str]) -> bool:
    lowered = url.lower()
    return any(marker.lower() in lowered for marker in login_url_markers)


def check_session(session: Session, base_url: str, login_url_markers: Iterable[str], timeout_ms: int) -> tuple[bool, str]:
    """Navigate to the Blackboard landing page and check whether we got
    bounced to a login/SSO page, which means the saved session is dead.
    Returns (looks_logged_in, final_url) - the URL is included so a
    failure says what page was actually reached instead of just "expired",
    which matters because "expired" is being used as a catch-all for
    several different failure modes in practice (genuine SSO bounce vs.
    something else entirely).

    Only needs the URL after any redirects have settled, not a fully
    rendered page, so this waits for "domcontentloaded" rather than
    "networkidle" - much less likely to time out than the full-page loads
    sync does elsewhere, and retried once for the cases where it still
    does (matching scraper/common.py's goto(), which this intentionally
    doesn't import to keep browser.py free of a dependency on the scraper
    package).
    """
    page = session.new_page()
    try:
        last_error: PlaywrightTimeoutError | None = None
        for _ in range(2):
            try:
                page.goto(base_url, wait_until="domcontentloaded", timeout=timeout_ms)
                return (not looks_like_login_page(page.url, login_url_markers), page.url)
            except PlaywrightTimeoutError as exc:
                last_error = exc
        assert last_error is not None
        raise last_error
    finally:
        page.close()


def is_logged_in(session: Session, base_url: str, login_url_markers: Iterable[str], timeout_ms: int) -> bool:
    ok, _ = check_session(session, base_url, login_url_markers, timeout_ms)
    return ok


def require_logged_in(session: Session, base_url: str, login_url_markers: Iterable[str], timeout_ms: int) -> None:
    ok, url = check_session(session, base_url, login_url_markers, timeout_ms)
    if not ok:
        raise SessionExpired(
            f"Saved Blackboard session has expired or was never established "
            f"(landed on {url!r} - compare against config/selectors.yaml's "
            f"login_url_markers). Run `python -m blackboard_sync login` to (re)authenticate."
        )


def interactive_login(profile_dir: Path, base_url: str, login_url_markers: Iterable[str], timeout_ms: int) -> bool:
    """Open a real, visible browser window for the user to log in through,
    including 2FA. Blocks on input() waiting for the user to confirm they've
    reached their dashboard, then verifies and persists the session.
    """
    with Session(profile_dir, headless=False) as session:
        page = session.new_page()
        page.goto(base_url, timeout=timeout_ms)
        print()
        print("A browser window has opened.")
        print("Log in and complete 2FA exactly as you normally would.")
        print("Once you can see your Blackboard dashboard/course list,")
        print("come back here and press Enter.")
        print()
        input("Press Enter once you're logged in... ")

        ok = is_logged_in(session, base_url, login_url_markers, timeout_ms)
        if ok:
            print("Looks good - session saved to", profile_dir)
        else:
            print(
                "Warning: this still looks like a login page "
                f"({page.url!r}). The session may not have been saved. "
                "Try again, and if it keeps happening, check "
                "config/selectors.yaml -> login_url_markers."
            )
        return ok
