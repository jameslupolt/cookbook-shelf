"""Shared, bounded query logic for CLI and MCP; independent of browser transport."""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .errors import LayoutChanged, ShelfError
from .parser import parse_page, shelf_url, tab_path


def _words(value: str) -> list[str]:
    return re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", value).casefold())


def contains_phrase(value: str, phrase: str) -> bool:
    wanted, words = _words(phrase), _words(value)
    return bool(wanted) and any(words[i:i + len(wanted)] == wanted for i in range(len(words)))


def query_url(route: str, query: str, kind: str = "recipes") -> str:
    parts = urlsplit(shelf_url(route))
    # Clear previous query, filters, and pagination from the tab URL.
    params = {"q": query}
    if kind == "books":
        params["view"] = "1"  # 200 books/page, with ISBN/index badges still present.
    # The default recipe view carries ingredient metadata; condensed recipes do not.
    return urlunsplit((parts.scheme, parts.netloc, tab_path(route), urlencode(params), ""))


class ShelfService:
    def __init__(self, transport):
        self.transport = transport

    def _collect(self, kind: str, query: str, *, limit: int, max_pages: int,
                 accept=None) -> dict:
        if not 1 <= limit <= 5000 or not 1 <= max_pages <= 100:
            raise ShelfError("limit must be 1–5000 and max_pages must be 1–100.")
        route = self.transport.route(kind)
        url = query_url(route, query, kind)
        seen_urls, seen_ids, items = set(), set(), []
        pages = examined = excluded = unknown = 0
        complete = False
        expected_total = None
        while url and pages < max_pages:
            if url in seen_urls:
                raise LayoutChanged("EYB pagination repeated a page; results would be incomplete.")
            seen_urls.add(url)
            document = self.transport.read(url)
            parsed = parse_page(document.html, document.url, kind, document.status)
            # Reject a redirect that drops/changes the submitted query or switches tabs.
            requested, actual = urlsplit(url), urlsplit(document.url)
            if (tab_path(document.url) != tab_path(url) or
                dict(parse_qsl(actual.query)).get("q", "") != dict(parse_qsl(requested.query)).get("q", "")):
                raise LayoutChanged("EYB redirected to a different search; results cannot be trusted.")
            pages += 1
            if parsed.total_count is not None:
                if expected_total is not None and expected_total != parsed.total_count:
                    raise LayoutChanged("EYB's result count changed during pagination; repeat the search.")
                expected_total = parsed.total_count
            stopped = False
            for index, item in enumerate(parsed.items):
                if item["id"] in seen_ids:
                    continue
                seen_ids.add(item["id"])
                examined += 1
                decision = accept(item) if accept else True
                if decision is None:
                    unknown += 1
                if not decision:
                    excluded += 1
                    continue
                items.append(item)
                if len(items) == limit:
                    stopped = index + 1 < len(parsed.items) or parsed.next_url is not None
                    break
            if len(items) == limit:
                complete = not stopped
                break
            url = parsed.next_url
            if url:
                if dict(parse_qsl(urlsplit(url).query)).get("q", "") != query:
                    raise LayoutChanged("EYB pagination changed the search query.")
            else:
                complete = True
        if complete and expected_total is not None and examined != expected_total:
            raise LayoutChanged("EYB's result count does not match the pages read; results would be incomplete.")
        return dict(items=items, count=len(items), pages_read=pages,
                    search_pages_complete=complete, truncated=not complete,
                    website_candidate_count=expected_total,
                    candidates_examined=examined, candidates_excluded=excluded,
                    candidates_with_missing_metadata=unknown)

    def list_cookbooks(self, limit: int = 500, max_pages: int = 20) -> dict:
        result = self._collect("books", "", limit=limit, max_pages=max_pages)
        result["scope"] = "cookbooks on your EYB Bookshelf"
        result["indexing"] = {
            "known_unindexed": [b["title"] for b in result["items"] if b["indexed"] is False],
            "unknown_status_count": sum(b["indexed"] is None for b in result["items"]),
        }
        return result

    def search_recipes(self, query: str, mode: str = "keyword", limit: int = 200,
                       max_pages: int = 20) -> dict:
        query = query.strip()
        if not 1 <= len(query) <= 200 or not _words(query):
            raise ShelfError("Enter a nonempty recipe query of at most 200 characters.")
        if mode not in ("keyword", "ingredient", "dish"):
            raise ShelfError("mode must be keyword, ingredient, or dish.")
        if not 1 <= limit <= 5000 or not 1 <= max_pages <= 100:
            raise ShelfError("limit must be 1–5000 and max_pages must be 1–100.")
        if mode != "keyword" and any(c in query for c in ('"', ':', '*', '\n', '\r')):
            raise ShelfError("Use plain ingredient/dish names; use keyword mode for EYB query operators.")
        books = self.list_cookbooks(limit=5000, max_pages=max_pages)
        if books["truncated"]:
            raise ShelfError("The cookbook list is incomplete. Increase --max-pages before searching.")
        book_ids = {b["id"] for b in books["items"]}

        def accept(item):
            if not item["book_id"]:
                return None
            if item["book_id"] not in book_ids:
                return False
            if mode == "ingredient":
                if item["ingredients"] is None:
                    return None
                matched = any(contains_phrase(value, query) for value in item["ingredients"])
                item["match_basis"] = "listed ingredient"
                return matched
            if mode == "dish":
                item["match_basis"] = "recipe title or category; may include a dish served with this item"
                return (contains_phrase(item["title"], query) or
                        any(contains_phrase(value, query) for value in item["categories"] or []))
            item["match_basis"] = "EYB keyword search"
            return True

        remote_query = query if mode == "keyword" else '"' + query + '"'
        result = self._collect("recipes", remote_query, limit=limit, max_pages=max_pages, accept=accept)
        result.update(query=query, mode=mode, scope="cookbooks on your EYB Bookshelf",
                      indexing=books["indexing"], warnings=[
            "Only indexed recipes returned by EYB's keyword search are candidates; this is not a full-text search of your books.",
            "Ingredient lists may omit pantry staples. Missing page numbers and metadata are reported as null.",
        ])
        if mode in ("ingredient", "dish"):
            result["warnings"].append(
                "Matching uses the entered words without synonym expansion. Ingredient mode checks listed ingredient phrases; "
                "dish mode checks title/category candidates and is not exhaustive taxonomy search."
            )
        if result["candidates_with_missing_metadata"]:
            result["warnings"].append("Some candidates lacked enough metadata to establish ownership or a match and were excluded.")
        return result
