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


def is_logged_in(session: Session, base_url: str, login_url_markers: Iterable[str], timeout_ms: int) -> bool:
    """Navigate to the Blackboard landing page and check whether we got
    bounced to a login/SSO page, which means the saved session is dead.
    """
    page = session.new_page()
    try:
        page.goto(base_url, wait_until="networkidle", timeout=timeout_ms)
        return not looks_like_login_page(page.url, login_url_markers)
    finally:
        page.close()


def require_logged_in(session: Session, base_url: str, login_url_markers: Iterable[str], timeout_ms: int) -> None:
    if not is_logged_in(session, base_url, login_url_markers, timeout_ms):
        raise SessionExpired(
            "Saved Blackboard session has expired or was never established. "
            "Run `python -m blackboard_sync login` to (re)authenticate."
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
