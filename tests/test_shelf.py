import asyncio
from urllib.parse import parse_qs, urlsplit

import pytest

from cookbook_shelf.browser import Document, profile_lock
from cookbook_shelf.cli import main
from cookbook_shelf.demo import DemoTransport
from cookbook_shelf.errors import LayoutChanged, LoginRequired, ScopeError, ShelfError, VerificationRequired
from cookbook_shelf.parser import parse_page, shelf_route, shelf_url
from cookbook_shelf.service import ShelfService, query_url

BASE = "https://www.eatyourbooks.com"


def book(bid="10", title="Example cookbook", badge="Indexed"):
    # Layout follows observed EYB markup, with completely fictional content.
    return f'''<div class="indexable"><div class="indexable-main"><div class="book-data">
    <h2><a class="BookTitleExp" href="/library/{bid}/example">{title}</a></h2>
    <a class="author">Example Author</a></div></div><div class="info-wrapper-small">
    <ul class="meta"><li class="isbn"><span class="spnISBN">ISBN: 0012345678901</span>
    <span class="index-status"><span>{badge}</span></span></li></ul></div></div>'''


def recipe(rid="100", bid="10", title="Spring bowl", ingredients="frozen edamame; rice", condensed=False):
    source = f'<a class="RecipeBookTitleExp main-title" href="/library/{bid}/example">Example cookbook</a>'
    if not condensed:
        source = f"<h3>from {source}</h3>"
    meta = "" if ingredients is None else f"<li><b>Ingredients:</b> {ingredients}</li>"
    return f'''<div class="indexable"><div class="indexable-main"><div class="book-data">
    <div class="book-title"><h2 class="title"><a class="RecipeTitleExp" href="/library/recipes/{rid}/example">{title}</a> (page 42)</h2>
    {source}<a class="author">Example Author</a></div></div></div><div class="info-wrapper-small">
    <ul class="meta"><li><b>Categories:</b> Salads; Main course</li>{meta}</ul></div></div>'''


class Pages:
    def __init__(self, recipes, books=None):
        self.recipes = recipes
        self.books = books or [book()]
        self.calls = []

    def route(self, kind):
        return BASE + ("/bookshelf/books" if kind == "books" else "/bookshelf")

    def read(self, url):
        self.calls.append(url)
        parts = urlsplit(url)
        is_books = "/books" in parts.path[len("/bookshelf"):]
        pages = self.books if is_books else self.recipes
        suffix = parts.path.rsplit("/", 1)[-1]
        page = int(suffix) if suffix.isdigit() else 1
        html = pages[page - 1]
        if page < len(pages):
            stem = "/bookshelf/books" if is_books else "/bookshelf"
            html += f'<a class="page-next" href="{stem}/{page+1}?{parts.query}">next</a>'
        return Document(html, url)


def test_realistic_mobile_book_metadata_and_leading_zero_isbn():
    item = parse_page(book(), BASE + "/bookshelf/books", "books").items[0]
    assert item["indexed"] is True
    assert item["isbn"] == "0012345678901"
    assert item["authors"] == ["Example Author"]


@pytest.mark.parametrize("condensed", [True, False])
def test_page_number_in_h2_and_metadata_outside_card(condensed):
    item = parse_page(recipe(condensed=condensed), BASE + "/bookshelf", "recipes").items[0]
    assert item["page"] == "42"
    assert item["book_id"] == "10"
    assert item["ingredients"] == ["frozen edamame", "rice"]


@pytest.mark.parametrize("badge,value", [("Not yet indexed", False), ("", None), ("Partially indexed", None)])
def test_unknown_indexing_is_not_invented(badge, value):
    assert parse_page(book(badge=badge), BASE + "/bookshelf/books", "books").items[0]["indexed"] is value


def test_relative_path_pagination_and_duplicates():
    pages = Pages([recipe(), recipe() + recipe("101")])
    data = ShelfService(pages).search_recipes("edamame", "ingredient")
    assert data["count"] == 2
    assert data["search_pages_complete"]
    assert data["pages_read"] == 2
    assert parse_qs(urlsplit(pages.calls[-1]).query)["q"] == ['"edamame"']


def test_ingredient_search_rejects_title_only_match_and_nonowned_book():
    pages = Pages([recipe("1") + recipe("2", title="Edamame-style salad", ingredients="peas; rice")
                   + recipe("3", bid="999")])
    data = ShelfService(pages).search_recipes("edamame", "ingredient")
    assert [r["id"] for r in data["items"]] == ["1"]
    assert data["candidates_excluded"] == 2


def test_missing_ingredient_metadata_is_reported():
    result = ShelfService(Pages([recipe(ingredients=None)])).search_recipes("edamame", "ingredient")
    assert result["count"] == 0
    assert result["candidates_with_missing_metadata"] == 1
    assert any("lacked enough" in w for w in result["warnings"])


def test_page_and_result_caps_are_explicit():
    result = ShelfService(Pages([recipe(), recipe("101")])).search_recipes("edamame", max_pages=1)
    assert result["truncated"]
    assert result["count"] == 1
    result = ShelfService(Pages([recipe() + recipe("101")])).search_recipes("edamame", limit=1)
    assert result["truncated"]


def test_limit_exactly_at_last_record_is_complete():
    result = ShelfService(Pages([recipe()])).search_recipes("edamame", limit=1)
    assert result["search_pages_complete"]


def test_missing_book_inventory_refuses_search():
    with pytest.raises(ShelfError, match="cookbook list is incomplete"):
        ShelfService(Pages([recipe()], [book(), book("11")])).search_recipes("edamame", max_pages=1)


def test_foreign_and_write_urls_are_rejected():
    for href in ["https://evil.example/bookshelf", "//evil.example/bookshelf", "/library/recipes",
                 "/bookshelf/import", "/bookshelf/add-personal-recipe", "http://www.eatyourbooks.com/bookshelf"]:
        with pytest.raises(ScopeError):
            shelf_url(href, BASE + "/bookshelf")


def test_foreign_next_page_is_rejected():
    html = recipe() + '<a class="page-next" href="https://evil.example/bookshelf/2">next</a>'
    with pytest.raises(ScopeError):
        parse_page(html, BASE + "/bookshelf", "recipes")


@pytest.mark.parametrize("html,url,status,error", [
    ("<title>Just a moment...</title>", BASE + "/signin", 403, VerificationRequired),
    ("<input type=password>", BASE + "/signin", 200, LoginRequired),
    ("Join now", BASE + "/public-bookshelf", 200, LoginRequired),
    ("<h1>Something changed</h1>", BASE + "/bookshelf", 200, LayoutChanged),
    ("<h1>Server error</h1>", BASE + "/bookshelf", 500, LayoutChanged),
])
def test_error_pages_are_not_empty_shelves(html, url, status, error):
    with pytest.raises(error):
        parse_page(html, url, "recipes", status)


def test_explicit_empty_results():
    assert parse_page('<div class="search-results">No results found</div>', BASE + "/bookshelf", "recipes").items == []


def test_zero_count_confirms_empty_results():
    result = parse_page('<b><span id="search-result-count">0</span> results</b>', BASE + "/bookshelf", "recipes")
    assert result.items == [] and result.total_count == 0


def test_missing_next_link_cannot_claim_complete_results():
    html = '<span id="search-result-count">2</span>' + recipe()
    with pytest.raises(LayoutChanged, match="count does not match"):
        ShelfService(Pages([html])).search_recipes("edamame")


def test_result_count_change_is_detected():
    html = '<span id="search-result-count">{}</span>'
    with pytest.raises(LayoutChanged, match="count changed"):
        ShelfService(Pages([html.format(2) + recipe(), html.format(3) + recipe("101")])).search_recipes("edamame")


def test_total_count_is_reported_and_checked_after_filtering():
    html = '<span id="search-result-count">2</span>' + recipe() + recipe("101", bid="999")
    result = ShelfService(Pages([html])).search_recipes("edamame")
    assert result["website_candidate_count"] == 2
    assert result["count"] == 1 and result["search_pages_complete"]


@pytest.mark.parametrize("query,mode,limit", [('rice:peas', 'ingredient', 10), ('salsa', 'dish', 0)])
def test_invalid_arguments_do_not_read_account(query, mode, limit):
    transport = Pages([recipe()])
    with pytest.raises(ShelfError):
        ShelfService(transport).search_recipes(query, mode, limit)
    assert transport.calls == []


def test_dropped_search_query_refuses_unfiltered_results():
    class Redirect(Pages):
        def read(self, url):
            doc = super().read(url)
            if urlsplit(url).path == "/bookshelf":
                doc.url = BASE + "/bookshelf"
            return doc
    with pytest.raises(LayoutChanged, match="different search"):
        ShelfService(Redirect([recipe()])).search_recipes("edamame")


def test_repeated_page_errors_instead_of_looping():
    html = recipe() + '<a class="page-next" href="/bookshelf?q=edamame">next</a>'
    with pytest.raises(LayoutChanged, match="repeated"):
        ShelfService(Pages([html])).search_recipes("edamame")


def test_query_encoding_does_not_inject_filters():
    url = query_url(BASE + "/bookshelf/3?q=stale", "rice & lemon")
    assert urlsplit(url).path == "/bookshelf"
    assert parse_qs(urlsplit(url).query) == {"q": ["rice & lemon"]}


def test_route_discovery_ignores_public_library_link():
    html = '<a href="/library">Books</a><a href="/bookshelf/books">Books</a>'
    assert shelf_route(html, "books", BASE + "/bookshelf") == BASE + "/bookshelf/books"


def test_profile_lock_excludes_second_process_and_cleans_up(tmp_path):
    with profile_lock(tmp_path):
        with pytest.raises(ShelfError, match="in use"):
            with profile_lock(tmp_path):
                pass
    assert not (tmp_path / "cookbook-shelf.lock").exists()


def test_cli_demo_and_json(capsys):
    import json
    assert main(["--demo", "--json", "search", "--ingredient", "edamame"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["demo"] is True
    assert result["items"][0]["title"] == "Spring bowl"


def test_mcp_tool_registration_and_real_protocol_call():
    from mcp import Client
    from cookbook_shelf.mcp_server import create_server

    async def exercise():
        async with Client(create_server(demo=True)) as client:
            tools = (await client.list_tools()).tools
            assert {tool.name for tool in tools} == {"list_cookbooks", "search_my_recipes"}
            for tool in tools:
                assert tool.annotations.read_only_hint is True
            result = await client.call_tool("search_my_recipes", {"query": "salsa", "mode": "dish"})
            assert not result.is_error
            assert "Roasted tomato salsa" in str(result)
    asyncio.run(exercise())


def test_mcp_stdio_subprocess():
    import sys
    from mcp import Client
    from mcp.client.stdio import StdioServerParameters

    async def exercise():
        parameters = StdioServerParameters(command=sys.executable,
            args=["-m", "cookbook_shelf.mcp_server"], env={"EYB_DEMO": "1"})
        async with Client(parameters) as client:
            listing = await client.call_tool("list_cookbooks", {})
            assert not listing.is_error
            assert "Demo Kitchen" in str(listing)
            result = await client.call_tool("search_my_recipes", {"query": "edamame", "mode": "ingredient"})
            assert not result.is_error
            assert "Spring bowl" in str(result)
            error = await client.call_tool("search_my_recipes", {"query": ""})
            assert error.is_error
    asyncio.run(asyncio.wait_for(exercise(), timeout=20))
