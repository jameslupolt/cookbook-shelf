# Cookbook Shelf

A small **read-only** Python CLI and MCP server for listing cookbooks on your
Eat Your Books shelf and finding recipe references in those books.

**Status: experimental; live CLI and MCP checks passed using regular Chrome
attachment.** Manually signing into a dedicated Chrome window, then connecting
with `EYB_CDP_URL`, successfully listed the test account's full book inventory
and searched its recipes across multiple pages. Version 0.2.1 also fixes Unicode
output when a Windows CLI command is piped or redirected. There are 54 automated
tests; see [VALIDATION.md](VALIDATION.md) for the live checks and their limits.

The original Playwright-launched login still stalls on Cloudflare. The verified
path is **Attach to regular Chrome**, below. An in-app browser login does not
automatically sign this separate Chrome profile in.

## Install

Requires Python 3.10+ and a supported desktop browser environment.

From this directory, with [uv](https://docs.astral.sh/uv/):

```sh
uv sync --extra mcp
```

Or with pip:

```sh
python -m pip install ".[mcp]"
```

After installation, follow **Attach to regular Chrome** below. Installed Google
Chrome is sufficient for attachment; `python -m playwright install chromium` is
only necessary for the original launcher mode. With uv, prefix `cookbooks`
commands below with `uv run`.

In the original launcher mode (without `EYB_CDP_URL`), `login` opens a dedicated
browser window. Sign in on EYB yourself, then press
Enter in the terminal. Session cookies stay in that local browser profile.
The tool does not ask for, log, or store your password in its configuration.
It does not solve CAPTCHAs, use stealth plugins, or bypass access checks. If EYB
blocks this browser, the tool reports that and stops; a browser-backed adapter
is not guaranteed to avoid verification challenges.

Version 0.1.1 explicitly enables Chromium's sandbox, correcting the original
launcher's `--no-sandbox` warning. This fixes a browser setting; it is not a
Cloudflare fix. If verification stays on screen for about a minute, cancel in
the terminal with Ctrl+C (or type `q`). If you press Enter while still challenged,
the tool reports the block without making another navigation request.
Cloudflare lists [automated browsers as unsupported for production challenges](https://developers.cloudflare.com/cloudflare-challenges/reference/supported-browsers/).

## Attach to regular Chrome (verified on the test account)

This option does not need a browser extension. Start Chrome yourself with a
dedicated data directory and a local debugging port. On Windows, for example:

```powershell
$env:EYB_PROFILE_DIR = Join-Path $env:LOCALAPPDATA 'cookbook-shelf\manual-chrome-profile'
$env:EYB_CDP_URL = 'http://127.0.0.1:9223'
$eybChrome = Join-Path $env:ProgramFiles 'Google\Chrome\Application\chrome.exe'
& $eybChrome "--user-data-dir=$env:EYB_PROFILE_DIR" --remote-debugging-address=127.0.0.1 --remote-debugging-port=9223 https://www.eatyourbooks.com/myhome
```

Sign in and reach your Bookshelf **before** running the CLI. Leave Chrome open.
Use this dedicated profile only for EYB. The local debugging endpoint controls
that browser; do not expose it on your network or use your everyday Chrome profile.

In the same terminal (after installing the package), run:

```powershell
cookbooks --json login
cookbooks --json list
cookbooks --json search --ingredient edamame --max-pages 6
```

With `EYB_CDP_URL` set, `login` only verifies access; it never opens a sign-in form
or asks for a password. Queries create and close their own temporary tab in the
existing browser context. They do not close Chrome or the tab you used to sign in.
`--headed` and `EYB_BROWSER_CHANNEL` apply only to launcher mode.
`--profile` / `EYB_PROFILE_DIR` coordinates command locking in attachment mode;
the attached browser itself determines the account and cookie profile.

You can also pass `--cdp-url http://127.0.0.1:9223` before a CLI subcommand.
Only HTTP endpoints at explicit loopback IP addresses and ports are accepted.
MCP uses the same `EYB_CDP_URL` and `EYB_PROFILE_DIR` environment variables; the
browser must already be open and signed in. No session credentials are copied.
If a query is challenged, it stops. This is not a guarantee that EYB will accept
automated searches after manual login.

## Use

```sh
uv run cookbooks list
uv run cookbooks search --ingredient edamame
uv run cookbooks search --dish salsa
uv run cookbooks search --query '"Ina Garten" chicken'
uv run cookbooks --json search --ingredient edamame
uv run cookbooks --headed search --dish salsa
```

Global switches (`--json`, `--headed`, `--profile`, `--cdp-url`, `--demo`) go **before** the
subcommand. Commands return exit code 2 for an actionable error and 130 on cancel.

- **Ingredient** searches quote the phrase in EYB's search and then match it
  against listed ingredients. This avoids treating every broader soybean match
  as edamame. Use one ingredient phrase per query; for several ingredients use
  `--query` with EYB's normal search syntax. Synonyms are not silently invented.
- **Dish** searches quote the phrase, then check titles and categories. Results
  may include "chicken with salsa" as well as standalone salsa recipes. This is
  candidate discovery, not exhaustive taxonomy classification.
- **Keyword** passes the query to EYB and retains results whose source book ID is
  on your shelf. EYB supports exact phrases, exclusions, and `title:` queries.
- Results preserve recipe and book links, authors, page numbers, ingredients,
  and categories when available. Unknown values stay null.
- All searches first obtain your book inventory and restrict results to those
  IDs. Bookshelf navigation is used exclusively; there is no global-library
  fallback and no book, bookmark, or note mutation endpoint.
- Book lists use the 200-entry condensed view. Recipe searches use the detailed
  view because condensed recipe lists omit ingredient metadata. On a mobile
  layout the parser also reads metadata beneath the expandable result.
- Pagination follows EYB's next links, with a one-second minimum interval
  between navigation requests. It stops at limits, repeated pages, redirects to
  other searches, login pages, and verification/rate-limit responses. Where EYB
  displays a result count, the tool checks it against the records traversed
  before claiming completion.

Defaults: up to 500 books or 200 matching recipes, and 20 pages per listing.
When limited, output explicitly says **PARTIAL** / `truncated: true`.

```sh
uv run cookbooks --json search --dish salsa --limit 1000 --max-pages 50
```

`search_pages_complete` means the returned EYB query pages were traversed. It
does **not** mean that every physical book was fully searchable. Check indexing
coverage and missing-metadata warnings. Unindexed books and incomplete indexes
cannot supply all of their recipes. No quantities, methods, or dietary safety
guarantees are inferred from index data.

## Try without an account

```sh
uv run cookbooks --demo list
uv run cookbooks --demo search --ingredient edamame
uv run cookbooks --demo --json search --dish salsa
```

Demo content is fictional and labeled as such. Demo mode makes no network calls
and does not start a browser.

## MCP

The MCP interface uses the same service as the CLI. Two tools are exposed:

- `list_cookbooks(limit=500, max_pages=20)`
- `search_my_recipes(query, mode="keyword", limit=200, max_pages=20)`

Both are annotated read-only. No credentials are accepted as tool arguments.
Login is performed separately in a terminal. Calls are serialized so the same
profile cannot be driven concurrently. In attachment mode each operation closes
only its own query tab and disconnects; Chrome remains open. In launcher mode it
closes its browser. Protocol output uses stdout; browser/login issues are tool errors.

Example Codex configuration (replace the directory with this project's actual
absolute path and use the same local OS account as `cookbooks login`):

```toml
[mcp_servers.cookbook_shelf]
command = "uv"
args = ["--directory", "/absolute/path/to/cookbook-shelf", "run", "--extra", "mcp", "cookbook-shelf-mcp"]
tool_timeout_sec = 180

[mcp_servers.cookbook_shelf.env]
EYB_CDP_URL = "http://127.0.0.1:9223"
EYB_PROFILE_DIR = "/absolute/path/to/dedicated-chrome-profile"
```

The local launcher does not need an OpenAI API key. Tool results are visible to
the assistant and therefore to whichever model provider your MCP client uses.

## Browser options

Environment variables are optional:

| Variable | Purpose |
| --- | --- |
| `EYB_PROFILE_DIR` | Dedicated profile directory shared by login, CLI, and MCP |
| `EYB_BROWSER_CHANNEL` | `chromium` (default), `chrome`, or `msedge` |
| `EYB_HEADED` | Set to `1` to show the MCP query browser |
| `EYB_DEMO` | Set to `1` for the MCP server's fictional demonstration mode |
| `EYB_CDP_URL` | Attach to a dedicated, already-running local Chrome window |

Do not point the tool at your normal browser profile. The default is
`%LOCALAPPDATA%/cookbook-shelf/browser-profile` on Windows, the equivalent
Application Support folder on macOS, or the XDG data folder on Linux.
This profile contains session credentials. Keep it out of Git and shared folders.
Use the same browser channel for login and subsequent queries.

## Tests

```sh
uv sync --extra mcp --extra dev
uv run pytest
```

Tests exercise current-style mobile/condensed markup, recipe page numbers,
ingredient matching, cookbook ownership, pagination, truncation, missing data,
query encoding, expired sessions, verification pages, profile locking, CLI JSON,
and MCP tool calls. They use synthetic fixtures rather than member data.
See [VALIDATION.md](VALIDATION.md) for the checks run and remaining limitations.

## Origin and access terms

This implementation was written independently. The prior
[lampholder/eat-your-books wrapper](https://github.com/lampholder/eat-your-books)
was reviewed as a reference. It has no declared license and contains syntax
errors, so none of its code was copied or vendored. The implementation also
accounts for observed current differences: page numbers in recipe headings,
metadata moved outside `.book-data`, and path-based pagination.

This project's MIT license covers our code, not EYB content or access rights.
It is unaffiliated with Eat Your Books / CookShelf. EYB's
[terms](https://www.eatyourbooks.com/terms-and-conditions) restrict automated
access and AI-related use; this implementation does not confer permission or
resolve those restrictions. A user's normal browser session is an authentication
mechanism, not an exemption. No database of EYB content is distributed here.

References: [EYB search documentation](https://support.eatyourbooks.com/article/275-searching-for-recipes-in-your-bookshelf),
[MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk),
[Playwright Python](https://playwright.dev/python/docs/library).
