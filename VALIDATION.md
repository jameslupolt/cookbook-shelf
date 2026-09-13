# Validation — September 12, 2026

## Passed

- 54 automated tests on Windows, Python 3.10.19: parsing, book ownership,
  ingredient matching, explicit partial results, pagination totals, dropped
  queries, redirects, expired sessions, verification pages, and profile locking.
- Browser-launch sandbox setting, cancellation cleanup, unresolved-challenge
  detection without an extra request, and verification after manual sign-in
  are covered using a simulated browser (no live challenge solving).
- CDP attachment tests reject remote endpoints, verify ownership/cleanup of only
  the tool's new tab, leave the external browser/context open on success and
  failure, verify sign-in without prompting, and handle an unavailable endpoint.

- Unicode recipe names through JSON and text output starting from a Windows
  cp1252 stream. Version 0.2.1 explicitly writes UTF-8 output.
- CLI demo JSON output.
- MCP v2.2 tool discovery and calls through both the in-process client and an
  actual stdio subprocess. The subprocess exercises both tools and an error.
- An observed authenticated recipe-card fragment parsed into the expected
  title, source book, page number, authors, and 12 listed ingredients. That
  fragment remains outside the distributed source; tests contain fictional data.

## Live site inspection

A manually authenticated browser was used to inspect the current Bookshelf
tabs, condensed book view, detailed recipe view, page links, result-count markup,
and searches for edamame and salsa. Example source-book IDs were checked against
the signed-in book inventory. The live observations informed the parser and
synthetic regression fixtures.

This was a browser inspection, not a successful standalone CLI login test.
The tool's persistent browser profile is separate from the inspecting browser.

## First standalone login attempt: blocked

The user's Chrome window remained on Cloudflare's verification page before the
EYB login form. It also displayed a `--no-sandbox` launch warning. Version 0.1.1
enables Chromium sandboxing and improves cancellation/diagnostics. These are
tested code corrections, not evidence that the live verification loop is fixed.

## Second standalone login attempt: still blocked

After installing 0.1.1 and passing all 38 tests against that installed version,
the user retried login. Cloudflare verification stalled again and the user
exited. The sandbox correction did not resolve authentication. Repeating this
same login is not a useful acceptance test at this point.

## Live Chrome attachment acceptance: passed

The user started regular Chrome with a dedicated data directory and loopback
debugging port, then signed in manually before the CLI attached.

- CLI `login`: authenticated Bookshelf access verified.
- CLI `list`: 192 books, one condensed page, matching EYB's total; not truncated.
- CLI ingredient search for edamame: six pages, 140 website candidates examined,
  62 retained after ownership and explicit ingredient matching, 78 excluded,
  zero candidates missing required metadata, and no truncation.
- The first ingredient run exposed a Windows cp1252 output failure on a macron
  in a recipe title. Version 0.2.1 fixed the output encoding; the rerun passed.
- A separate live MCP stdio process discovered both tools. `list_cookbooks`
  returned all 192 books; `search_my_recipes` returned a deliberately bounded
  five-result salsa sample, correctly marked partial, all from owned books.
- Multiple independent CLI/MCP connections reused the browser's authenticated
  session. Queries disconnected without closing the user's Chrome window.

Live account result files are outside the source package. The test used an
already-open browser on one Windows machine/account. Login retention after a
Chrome restart, other operating systems/accounts, long-term challenge behavior,
have not been tested. A subsequent check through the registered Codex MCP tool
successfully listed a bounded sample of the authenticated Bookshelf and reported
truncation correctly. Downloading a matching title with a separate Anna's Archive
MCP was also verified; downloading is outside this project's functionality.

## Reproduce the live check

With the dedicated Chrome window signed in and `EYB_CDP_URL` set:

```sh
cookbooks --json list
cookbooks --json search --ingredient edamame
cookbooks --json search --dish salsa
```

Compare the book count and a few recipe/book/page references to the website.
The standalone browser may encounter a verification challenge; successful
manual access in another browser does not prove this profile will be accepted.
Login retention across browser restarts and headless operation remain unproven.
Live multi-page collection passed with the window open. Demo tests alone do not
establish browser access.

The package is an experimental implementation, not an EYB-supported integration.
