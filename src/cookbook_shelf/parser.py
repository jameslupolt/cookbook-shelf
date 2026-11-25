"""Parse book/recipe references, preserving unknowns and detecting broken layouts.

Selectors were checked against authenticated EYB pages on 2026-09-12. Fixtures
are synthetic. No recipe methods, member notes, cookies, or scripts are returned.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag

from .errors import LayoutChanged, LoginRequired, ScopeError, VerificationRequired

ORIGIN = "https://www.cookshelf.app"
ALLOWED_HOSTS = frozenset({"www.eatyourbooks.com", "cookshelf.app", "www.cookshelf.app"})
BOOK_ID = re.compile(r"^/(?:library/|books/)(\d+)(?:/|$)")
RECIPE_ID = re.compile(r"^/(?:library/recipes|recipes)/(\d+)(?:/|$)")


def text(node: Tag | None) -> str:
    return node.get_text(" ", strip=True) if node else ""


def eyb_url(href: str, base: str = ORIGIN) -> str:
    url = urljoin(base, href)
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS
            or parts.port not in (None, 443) or parts.username or parts.password):
        raise ScopeError("Refusing a link outside the HTTPS Eat Your Books / CookShelf origin.")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def shelf_url(href: str, base: str = ORIGIN) -> str:
    url = eyb_url(href, base)
    parts = urlsplit(url)
    path = parts.path.rstrip("/")
    if path == "/search":
        params = parse_qs(parts.query)
        if params.get("scope") != ["shelf"]:
            raise ScopeError("Refusing public Library search; only shelf-scoped queries are accepted.")
        return url
    if not re.fullmatch(r"/(?:bookshelf(?:/books)?|shelf(?:/[\w-]+)?)(?:/\d+)?", path):
        raise ScopeError("The page left your shelf; public Library results are not accepted.")
    return url


def tab_path(url: str) -> str:
    """EYB numbers pages in the path, e.g. /shelf/books/2."""
    return re.sub(r"/\d+/?$", "", urlsplit(shelf_url(url)).path).rstrip("/")


def check_verification(html: str, status: int = 200) -> BeautifulSoup:
    soup = BeautifulSoup(html, "html.parser")
    title = text(soup.title).casefold()
    if status in (403, 429) or "just a moment" in title or soup.select_one("#challenge-form"):
        raise VerificationRequired(
            "EYB requires browser verification or has limited access. If 'cookbooks login' "
            "stalls on verification, this browser adapter is blocked; use the normal website. "
            "Repeated login attempts or changing your password will not resolve a browser challenge."
        )
    return soup


def check_page(html: str, url: str, status: int = 200) -> BeautifulSoup:
    soup = check_verification(html, status)
    if urlsplit(url).path.startswith(("/signin", "/public-bookshelf")):
        raise LoginRequired("Sign in first with 'cookbooks login'. Your session may have expired.")
    if status >= 400:
        raise LayoutChanged(f"EYB returned HTTP {status}; no results can be confirmed.")
    shelf_url(url)
    if soup.select_one('input[type="password"]') and not soup.select_one(".book-data"):
        raise LoginRequired("EYB displayed a sign-in form. Run 'cookbooks login'.")
    return soup


def shelf_route(html: str, kind: str, current_url: str) -> str:
    soup = check_page(html, current_url)
    label = "books" if kind == "books" else "recipes"
    for link in soup.select("a[href]"):
        if text(link).casefold() != label:
            continue
        try:
            return shelf_url(str(link["href"]), current_url)
        except ScopeError:
            continue
    raise LayoutChanged(f"Could not identify the {label} tab on your Bookshelf.")


def _reference(link: Tag, pattern: re.Pattern, base: str = ORIGIN) -> tuple[str, str] | None:
    if not link or not link.get("href"):
        return None
    url = eyb_url(str(link["href"]), base)
    match = pattern.match(urlsplit(url).path)
    return (match.group(1), url) if match else None


def _metadata(card: Tag, name: str) -> list[str] | None:
    for entry in card.select("ul.meta li"):
        raw = text(entry)
        match = re.match(rf"^{name}\s*:\s*(.*)$", raw, re.I)
        if match:
            return [value.strip() for value in match[1].split(";") if value.strip()]
    return None


def _book(card: Tag) -> dict | None:
    if card.name == "a":
        link, scope = card, card
    else:
        link = card.select_one('h2 a.full-title, h2 a.main-title, h2 a[href^="/library/"]')
        scope = card.find_parent(class_="indexable") or card
    ref = _reference(link, BOOK_ID)
    if not ref:
        return None
    img = link.select_one("img[alt]") if link is not None else None
    cover_title = str(img["alt"]) if img and img.get("alt") else ""
    index_text = " ".join(text(x) for x in scope.select(
        '[class*="pill"], .index-status, .indexing-status, [class*="index"]'
    )).casefold()
    indexed = None
    if re.search(r"not (?:yet )?indexed|unindexed|request (?:an )?index", index_text):
        indexed = False
    elif re.search(r"\bindexed\b", index_text) and not re.search(r"partially|indexing", index_text):
        indexed = True
    isbn = text(scope.select_one(".spnISBN"))
    isbn = re.sub(r"^ISBN:\s*", "", isbn).strip() or None
    title = text(link) if link.name == "a" and text(link) else ""
    title = title or cover_title or ""
    authors = [text(a) for a in scope.select("a.author")]
    return dict(id=ref[0], title=title, authors=authors,
                url=ref[1], indexed=indexed, isbn=isbn)


def _recipe(card: Tag) -> dict | None:
    modern = card.select_one(".rt-title") is not None
    if modern:
        link = card.select_one('a[href*="/recipes/"]')
    else:
        link = card.select_one('h2 a.RecipeTitleExp, h2 a[href*="/library/recipes/"]')
    ref = _reference(link, RECIPE_ID)
    if not ref:
        return None
    if modern:
        source_link = card.select_one('a[href^="/books/"], a[href^="/library/"]')
        source_ref = _reference(source_link, BOOK_ID)
        page_text = text(card.select_one(".rt-page"))
        page = re.search(r"\d+(?:\s*[-–,]\s*\d+)*", page_text)
        by = card.select_one(".rt-meta-by")
        names = card.select_one(".rt-ingredients-names")
        ingredients = ([v.strip() for v in re.split(r"[;,]", text(names)) if v.strip()]
                       if names is not None else None)
        return dict(id=ref[0], title=text(card.select_one(".rt-title")) or text(link), url=ref[1],
                    book_id=source_ref[0] if source_ref else None,
                    book_title=text(source_link) or None,
                    book_url=source_ref[1] if source_ref else None,
                    authors=[text(by)] if by is not None else [],
                    page=page[0] if page else None,
                    ingredients=ingredients,
                    categories=None)
    source_link = card.select_one('a.RecipeBookTitleExp.full-title, a.RecipeBookTitleExp.main-title, h3 a.full-title, h3 a.main-title, h3 a[href^="/library/"]')
    source_ref = _reference(source_link, BOOK_ID)
    page = re.search(r"\bpages?\s+([\d]+(?:\s*[-–,]\s*\d+)*)", text(card.select_one(".book-title")) or text(card), re.I)
    scope = card.find_parent(class_="indexable") or card
    return dict(id=ref[0], title=text(link), url=ref[1],
                book_id=source_ref[0] if source_ref else None,
                book_title=text(source_link) or None,
                book_url=source_ref[1] if source_ref else None,
                authors=[text(a) for a in card.select("a.author")],
                page=page[1] if page else None,
                ingredients=_metadata(scope, "Ingredients"),
                categories=_metadata(scope, "Categories"))


@dataclass
class ParsedPage:
    items: list[dict]
    next_url: str | None
    total_count: int | None = None


def parse_page(html: str, url: str, kind: str, status: int = 200) -> ParsedPage:
    soup = check_page(html, url, status)
    count_text = (text(soup.select_one("#search-result-count"))
                  or text(soup.select_one(".se-scope-tab.on .se-scope-count"))).replace(",", "")
    total_count = int(count_text) if count_text.isdecimal() else None
    cards = soup.select(".book-data") or soup.select("article.rt-card")
    if not cards and kind == "books":
        cards = soup.select("a.sh-cover-link")
    records = []
    for card in cards:
        item = (_book if kind == "books" else _recipe)(card)
        if item is None:
            raise LayoutChanged("A result could not be parsed; refusing to silently omit it.")
        records.append(item)
    if not cards:
        container = soup.select_one("#search-results, .search-results, .no-results, #no-results, .se-results")
        empty = text(container).casefold()
        if total_count != 0 and not re.search(r"no (?:matching )?(?:results|recipes|books)|0 results|bookshelf is empty|shelf is empty", empty):
            raise LayoutChanged("No recognizable results or explicit empty-results message was found.")
    next_link = soup.select_one('a.page-next[href], a[rel="next"][href], a[aria-label="Next"][href]')
    next_url = None
    if next_link and "disabled" not in next_link.get("class", []) and next_link.get("aria-disabled") != "true":
        next_url = shelf_url(str(next_link["href"]), url)
        if tab_path(next_url) != tab_path(url):
            raise ScopeError("Pagination changed the shelf tab unexpectedly.")
    return ParsedPage(records, next_url, total_count)
