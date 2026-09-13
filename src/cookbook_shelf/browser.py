"""Normal browser session, with manual login and no challenge-solving behavior."""

from __future__ import annotations

import os
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
from .errors import ShelfError
from .parser import ORIGIN, check_page, check_verification, shelf_route, shelf_url


@dataclass
class Document:
    html: str
    url: str
    status: int = 200


def profile_directory() -> Path:
    custom = os.environ.get("EYB_PROFILE_DIR")
    if custom:
        return Path(custom).expanduser().resolve()
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    return base / "cookbook-shelf" / "browser-profile"


@contextmanager
def profile_lock(profile: Path):
    profile.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = profile / "cookbook-shelf.lock"
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ShelfError(
            "This browser profile is in use. Close other cookbook-shelf commands. If a prior process "
            "crashed, confirm it has stopped before removing cookbook-shelf.lock from the profile."
        ) from None
    try:
        os.write(fd, str(os.getpid()).encode("ascii"))
        os.close(fd)
        yield
    finally:
        path.unlink(missing_ok=True)


def local_cdp_url(value: str) -> str:
    """Only attach to a browser debugging endpoint on this computer."""
    try:
        parts = urlsplit(value)
        valid = (parts.scheme == "http" and parts.hostname in ("127.0.0.1", "::1")
                 and parts.port is not None and 1 <= parts.port <= 65535
                 and not parts.username and not parts.password
                 and parts.path in ("", "/") and not parts.query and not parts.fragment)
    except ValueError:
        valid = False
    if not valid:
        raise ShelfError("Use a local Chrome endpoint such as http://127.0.0.1:9223 (no credentials or path).")
    return value.rstrip("/")


@contextmanager
def browser_transport(*, profile: Path | None = None, headed: bool = False,
                      cdp_url: str | None = None):
    from playwright.sync_api import Error, sync_playwright

    selected = (profile or profile_directory()).resolve()
    endpoint = cdp_url or os.environ.get("EYB_CDP_URL")
    if endpoint:
        endpoint = local_cdp_url(endpoint)
    channel = os.environ.get("EYB_BROWSER_CHANNEL", "chromium")
    if not endpoint and channel not in ("chromium", "chrome", "msedge"):
        raise ShelfError("EYB_BROWSER_CHANNEL must be chromium, chrome, or msedge.")
    with profile_lock(selected):
        try:
            with sync_playwright() as p:
                if endpoint:
                    browser = p.chromium.connect_over_cdp(endpoint, timeout=15000, no_defaults=True)
                    if not browser.contexts:
                        raise ShelfError("The Chrome connection has no default browser context.")
                    # Create our own tab. Do not read, select, or change the user's other tabs.
                    page = browser.contexts[0].new_page()
                    try:
                        page.set_default_timeout(15000)
                        page.set_default_navigation_timeout(30000)
                        yield BrowserTransport(page, attached=True)
                    finally:
                        if not page.is_closed():
                            page.close()
                    # Exiting sync_playwright disconnects the driver. The external
                    # browser and its default context belong to the user; never close them.
                    return
                context = p.chromium.launch_persistent_context(
                    str(selected), channel=channel, headless=not headed,
                    accept_downloads=False, chromium_sandbox=True,
                )
                try:
                    page = context.pages[0] if context.pages else context.new_page()
                    page.set_default_timeout(15000)
                    page.set_default_navigation_timeout(30000)
                    yield BrowserTransport(page)
                finally:
                    context.close()
        except Error:
            if endpoint:
                raise ShelfError(
                    "Could not communicate with the dedicated Chrome window. Keep it open, "
                    "check EYB_CDP_URL, and sign in there manually before retrying the query."
                ) from None
            # Browser errors can contain local paths and request details; keep them out of MCP.
            raise ShelfError(
                "The browser could not complete the operation. Install its runtime with "
                "'python -m playwright install chromium', close conflicting browser sessions, "
                "or run 'cookbooks login' in a terminal to inspect the website."
            ) from None


class BrowserTransport:
    def __init__(self, page, *, attached=False):
        self.page = page
        self.attached = attached
        self.routes = {}
        self.last_read = 0.0

    def read(self, url: str) -> Document:
        shelf_url(url)
        time.sleep(max(0, 1 - (time.monotonic() - self.last_read)))
        response = self.page.goto(url, wait_until="domcontentloaded")
        self.last_read = time.monotonic()
        # Do not retry, impersonate another browser, solve challenges, or request cookies.
        document = Document(self.page.content(), self.page.url, response.status if response else 200)
        check_page(document.html, document.url, document.status)
        return document

    def route(self, kind: str) -> str:
        if kind not in self.routes:
            document = self.read(ORIGIN + "/bookshelf")
            for name in ("books", "recipes"):
                self.routes[name] = shelf_route(document.html, name, document.url)
        return self.routes[kind]

    def login(self):
        if self.attached:
            # The user signs in before attachment. This command only verifies access.
            self.read(ORIGIN + "/bookshelf")
            return
        print("Opening EYB sign-in. Press Ctrl+C in this terminal to cancel.", file=sys.stderr, flush=True)
        self.page.goto(ORIGIN + "/signin", wait_until="domcontentloaded")
        print("Sign in yourself in the browser. This dedicated profile keeps the session locally.", file=sys.stderr)
        print(
            "If 'Verifying...' stays on screen for about a minute, cancel with Ctrl+C or type q below. "
            "Cloudflare may reject this automated browser; changing your password will not resolve that. "
            "No automatic refresh or challenge solving is performed.", file=sys.stderr,
        )
        answer = input("After signing in, press Enter to verify your Bookshelf (or q to cancel): ")
        if answer.strip().casefold() == "q":
            raise KeyboardInterrupt
        # Use the current DOM: the original navigation's 403 can be stale if the
        # user completed verification. Do not navigate again while still challenged.
        check_verification(self.page.content())
        self.read(ORIGIN + "/bookshelf")
