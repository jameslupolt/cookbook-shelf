from unittest.mock import MagicMock

import pytest

from cookbook_shelf.browser import BrowserTransport, browser_transport, local_cdp_url
from cookbook_shelf.errors import ShelfError, VerificationRequired


@pytest.fixture(autouse=True)
def isolated_cdp_environment(monkeypatch):
    monkeypatch.delenv("EYB_CDP_URL", raising=False)


def test_browser_keeps_sandbox_and_cleans_up_on_cancel(monkeypatch, tmp_path):
    driver = MagicMock()
    context = driver.__enter__.return_value.chromium.launch_persistent_context.return_value
    monkeypatch.setattr("playwright.sync_api.sync_playwright", lambda: driver)
    monkeypatch.setenv("EYB_BROWSER_CHANNEL", "chrome")
    with pytest.raises(KeyboardInterrupt):
        with browser_transport(profile=tmp_path, headed=True):
            raise KeyboardInterrupt
    launch = driver.__enter__.return_value.chromium.launch_persistent_context
    assert launch.call_args.kwargs["chromium_sandbox"] is True
    assert launch.call_args.kwargs["headless"] is False
    context.close.assert_called_once()
    assert not (tmp_path / "cookbook-shelf.lock").exists()


def test_login_does_not_reload_an_unresolved_challenge(monkeypatch, capsys):
    page = MagicMock()
    page.content.return_value = "<title>Just a moment...</title>"
    monkeypatch.setattr("builtins.input", lambda prompt: "")
    with pytest.raises(VerificationRequired, match="adapter is blocked"):
        BrowserTransport(page).login()
    page.goto.assert_called_once()
    assert "Ctrl+C" in capsys.readouterr().err


def test_login_verifies_after_challenge_is_cleared(monkeypatch):
    page = MagicMock()
    page.content.return_value = "<title>Just a moment...</title>"
    page.goto.return_value.status = 403

    def sign_in(prompt):
        page.content.return_value = '<a href="/bookshelf">My Bookshelf</a>'
        page.url = "https://www.eatyourbooks.com/bookshelf"
        page.goto.return_value.status = 200
        return ""

    monkeypatch.setattr("builtins.input", sign_in)
    BrowserTransport(page).login()
    assert page.goto.call_count == 2
    assert page.goto.call_args.args == ("https://www.eatyourbooks.com/bookshelf",)


def test_login_can_be_cancelled_without_another_request(monkeypatch):
    page = MagicMock()
    monkeypatch.setattr("builtins.input", lambda prompt: "q")
    with pytest.raises(KeyboardInterrupt):
        BrowserTransport(page).login()
    page.goto.assert_called_once()
    page.content.assert_not_called()


@pytest.mark.parametrize("url", [
    "http://example.com:9223", "http://localhost:9223", "https://127.0.0.1:9223",
    "http://127.0.0.1", "http://user:secret@127.0.0.1:9223", "http://127.0.0.1:9223/json",
    "http://127.0.0.1:9223/?token=x", "http://127.0.0.1:9223/#x", "http://127.0.0.1:invalid",
])
def test_cdp_rejects_remote_or_ambiguous_endpoints(url):
    with pytest.raises(ShelfError, match="local Chrome endpoint"):
        local_cdp_url(url)


def test_cdp_accepts_only_explicit_local_endpoints():
    assert local_cdp_url("http://127.0.0.1:9223/") == "http://127.0.0.1:9223"
    assert local_cdp_url("http://[::1]:9223") == "http://[::1]:9223"


@pytest.mark.parametrize("fail", [False, True])
def test_cdp_owns_only_its_new_tab(monkeypatch, tmp_path, fail):
    driver = MagicMock()
    chromium = driver.__enter__.return_value.chromium
    browser = chromium.connect_over_cdp.return_value
    context = MagicMock()
    browser.contexts = [context]
    page = context.new_page.return_value
    page.is_closed.return_value = False
    monkeypatch.setattr("playwright.sync_api.sync_playwright", lambda: driver)
    monkeypatch.setenv("EYB_CDP_URL", "http://127.0.0.1:9223")

    def exercise():
        with browser_transport(profile=tmp_path) as transport:
            assert transport.attached and transport.page is page
            if fail:
                raise VerificationRequired("challenge")

    if fail:
        with pytest.raises(VerificationRequired):
            exercise()
    else:
        exercise()
    chromium.connect_over_cdp.assert_called_once_with("http://127.0.0.1:9223", timeout=15000, no_defaults=True)
    chromium.launch_persistent_context.assert_not_called()
    context.new_page.assert_called_once()
    page.close.assert_called_once()
    context.close.assert_not_called()
    browser.close.assert_not_called()
    driver.__exit__.assert_called_once()
    assert not (tmp_path / "cookbook-shelf.lock").exists()


def test_cdp_login_checks_shelf_without_signin_navigation_or_prompt(monkeypatch):
    page = MagicMock()
    page.content.return_value = '<a href="/bookshelf">My Bookshelf</a>'
    page.url = "https://www.eatyourbooks.com/bookshelf"
    page.goto.return_value.status = 200
    prompt = MagicMock(side_effect=AssertionError("CDP login must not prompt"))
    monkeypatch.setattr("builtins.input", prompt)
    BrowserTransport(page, attached=True).login()
    page.goto.assert_called_once_with("https://www.eatyourbooks.com/bookshelf", wait_until="domcontentloaded")
    prompt.assert_not_called()


def test_unreachable_cdp_has_actionable_error_and_releases_lock(monkeypatch, tmp_path):
    from playwright.sync_api import Error
    driver = MagicMock()
    driver.__enter__.return_value.chromium.connect_over_cdp.side_effect = Error("private browser details")
    monkeypatch.setattr("playwright.sync_api.sync_playwright", lambda: driver)
    with pytest.raises(ShelfError, match="Keep it open") as caught:
        with browser_transport(profile=tmp_path, cdp_url="http://127.0.0.1:9223"):
            pass
    assert "private browser details" not in str(caught.value)
    assert not (tmp_path / "cookbook-shelf.lock").exists()
