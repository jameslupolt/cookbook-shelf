from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .browser import browser_transport
from .errors import ShelfError
from .service import ShelfService


def main(argv=None) -> int:
    # Recipe names contain characters outside Windows' legacy pipe encoding.
    # UTF-8 is the CLI output format for both JSON and text, including redirection.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Read-only personal cookbook lookup (experimental EYB adapter).")
    parser.add_argument("--demo", action="store_true", help="Use fictional sample data; no browser or account needed")
    parser.add_argument("--json", action="store_true", help="Print structured JSON")
    parser.add_argument("--headed", action="store_true", help="Show the query browser")
    parser.add_argument("--profile", type=Path, help="Dedicated browser profile (default: local app data)")
    parser.add_argument("--cdp-url", default=os.environ.get("EYB_CDP_URL"),
                        help="Connect to an already-open dedicated Chrome window, e.g. http://127.0.0.1:9223")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("login", help="Sign in manually in a browser; keep the session locally")
    for name in ("list", "search"):
        command = commands.add_parser(name)
        command.add_argument("--limit", type=int, default=500 if name == "list" else 200)
        command.add_argument("--max-pages", type=int, default=20)
        if name == "search":
            queries = command.add_mutually_exclusive_group(required=True)
            queries.add_argument("--query", help="EYB keyword search")
            queries.add_argument("--ingredient", help="Match the entered phrase in listed ingredients")
            queries.add_argument("--dish", help="Match title/category candidates; may include served-with dishes")
    args = parser.parse_args(argv)

    def run(transport):
        if args.command == "login":
            transport.login()
            return {"authenticated": True}
        service = ShelfService(transport)
        if args.command == "list":
            return service.list_cookbooks(args.limit, args.max_pages)
        query = args.ingredient or args.dish or args.query
        mode = "ingredient" if args.ingredient else "dish" if args.dish else "keyword"
        return service.search_recipes(query, mode, args.limit, args.max_pages)

    try:
        if args.demo:
            if args.command == "login":
                raise ShelfError("Demo mode does not use an account. Try '--demo list'.")
            from .demo import DemoTransport
            result = run(DemoTransport())
            result["demo"] = True
        else:
            if args.command == "login" and not args.cdp_url and not sys.stdin.isatty():
                raise ShelfError("Run 'cookbooks login' yourself in an interactive terminal.")
            with browser_transport(profile=args.profile, headed=args.headed or args.command == "login",
                                   cdp_url=args.cdp_url) as transport:
                result = run(transport)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "login":
            print("Bookshelf access verified.")
        else:
            if args.demo:
                print("DEMO — fictional examples, not your Bookshelf")
            for item in result["items"]:
                if args.command == "list":
                    status = {True: "indexed", False: "not indexed", None: "indexing unknown"}[item["indexed"]]
                    print(f"{item['title']} | {', '.join(item['authors'])} | {status}")
                else:
                    print(f"{item['title']} | {item['book_title']} | page {item['page'] or 'unknown'}")
                    print(f"  {item['url']}")
            print(f"{result['count']} results; {result['pages_read']} result pages read.")
            if result["truncated"]:
                print("PARTIAL: increase --limit or --max-pages to retrieve more.")
            for warning in result.get("warnings", []):
                print(f"Note: {warning}")
            coverage = result.get("indexing", {})
            if coverage.get("known_unindexed") or coverage.get("unknown_status_count"):
                print("Indexing coverage: " + json.dumps(coverage, ensure_ascii=False))
        return 0
    except ShelfError as exc:
        if args.json:
            print(json.dumps({"error": {"code": exc.code, "message": str(exc)}}))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return 2
    except (KeyboardInterrupt, EOFError):
        print("Cancelled.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
