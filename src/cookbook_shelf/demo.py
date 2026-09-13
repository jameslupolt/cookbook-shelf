"""Synthetic transport for installation checks; never represents the user's shelf."""

from urllib.parse import parse_qs, urlsplit

from .browser import Document


class DemoTransport:
    def route(self, kind):
        return "https://www.eatyourbooks.com/bookshelf" + ("/books" if kind == "books" else "")

    def read(self, url):
        if urlsplit(url).path.endswith("books"):
            html = '''<div class="book-data"><h2><a class="full-title" href="/library/900001/demo-kitchen">Demo Kitchen (fictional)</a></h2><a class="author">Example Author</a><span class="index-status">Indexed</span></div>'''
        else:
            query = parse_qs(urlsplit(url).query).get("q", [""])[0].casefold().strip('"')
            records = [
                ("900010", "Spring bowl", "edamame; rice; lemon", "Salads", "12"),
                ("900011", "Roasted tomato salsa", "tomatoes; onion; chilli", "Salsa; Sauces", "24"),
            ]
            html = ""
            for rid, title, ingredients, categories, page in records:
                if query and query not in " ".join((title, ingredients, categories)).casefold():
                    continue
                html += f'''<div class="book-data"><h2><a href="/library/recipes/{rid}/demo">{title}</a></h2><h3>from <a class="full-title" href="/library/900001/demo-kitchen">Demo Kitchen (fictional)</a> (page {page})</h3><a class="author">Example Author</a><ul class="meta"><li>Ingredients: {ingredients}</li><li>Categories: {categories}</li></ul></div>'''
            html = html or '<div class="search-results">No results found</div>'
        return Document(html, url)
