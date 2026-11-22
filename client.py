"""Fetch SnowFastAPI pages using a Snowflake connection or an interactive browser."""

import argparse
import json
import re
import sys
import time
from contextlib import closing
from http.client import HTTPSConnection
from urllib.parse import urlencode, urlsplit


def service_origin(url: str) -> str:
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    local = host in {"localhost", "127.0.0.1", "::1"}
    hosted = parsed.scheme == "https" and re.fullmatch(
        r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+snowflake\.app", host, re.ASCII
    )
    if not (hosted or (local and parsed.scheme in {"http", "https"})):
        raise ValueError("Use the HTTPS Snowflake serverless app URL or a loopback test server")
    authority = "[::1]" if host == "::1" else host
    if parsed.port is not None:
        authority += f":{parsed.port}"
    origin = f"{parsed.scheme}://{authority}"
    # Pass the browser the same ASCII origin we validated, allowing a single trailing slash.
    if not url.isascii() or url.lower() not in (origin, origin + "/"):
        raise ValueError("Supply just the service origin")
    return origin


def page_json(status: int, content_type: str, body: bytes, retry_after: str | None = None):
    if status != 200:
        guidance = {
            400: "This cursor is invalid for the dataset. Restart at page one.",
            401: "Sign in again. Use --cursor with the last successful page's next_cursor to resume.",
            403: "Check the role's access to the service, warehouse and published data.",
            404: "Check the dataset name against the service's /openapi.json.",
            409: "Ask the publisher to check the dataset's pagination key.",
            413: "Reduce --limit or ask the publisher for a narrower projection.",
            422: "Check --limit and --cursor against the route's limits in /openapi.json.",
            429: "All query slots are busy. Retry later.",
            500: "The service failed to build a page. Contact the publisher.",
            503: "Snowflake could not serve the page. Retry the request.",
            504: "Snowflake canceled the query or it timed out. Check query history.",
        }.get(status, "Check the service's HTTP response and availability.")
        if 300 <= status < 400:
            guidance = "Complete Snowflake sign-in. Use --cursor to resume a previous read."
        if status == 429 and retry_after and re.fullmatch(r"[0-9]{1,6}", retry_after):
            guidance = f"All query slots are busy. Retry after {retry_after} seconds."
        raise RuntimeError(f"Page request returned HTTP {status}. {guidance}")
    if content_type.partition(";")[0].strip().lower() != "application/json":
        raise RuntimeError(
            "HTTP 200 did not contain a JSON page. Check the service URL and sign-in."
        )
    try:
        page = json.loads(body)
    except (ValueError, UnicodeError):
        raise RuntimeError("HTTP 200 contained invalid JSON.") from None
    if (
        not isinstance(page, dict)
        or not isinstance(page.get("items"), list)
        or "next_cursor" not in page
        or not isinstance(page["next_cursor"], str | None)
    ):
        raise RuntimeError(
            "HTTP 200 did not contain a SnowFastAPI page with items and next_cursor."
        )
    return page


def read_pages(fetch, table: str, limit: int, count: int, cursor: str | None = None):
    path = f"/v1/tables/{table}"
    params = {"limit": str(limit)}
    if cursor is not None:
        params["cursor"] = cursor
    for _ in range(count):
        page = fetch(path, params)
        print(json.dumps(page, ensure_ascii=False), flush=True)
        if page["next_cursor"] is None:
            return
        params["cursor"] = page["next_cursor"]


def from_connection(args):
    import snowflake.connector

    options = {"role": args.role} if args.role else {}
    with closing(
        snowflake.connector.connect(connection_name=args.connection, paramstyle="qmark", **options)
    ) as conn:
        with closing(conn.cursor()) as db:
            db.execute("USE SECONDARY ROLES NONE")
            db.execute("DESCRIBE APPLICATION SERVICE IDENTIFIER(?)", (args.service,))
            fields = [f.name.lower() for f in db.description or ()]
            row = db.fetchone()
            if not row:
                raise RuntimeError("Snowflake did not return an Application Service")
            url = dict(zip(fields, row, strict=True))["url"] or ""
        origin = urlsplit(service_origin("https://" + url.removeprefix("https://")))
        if not (origin.hostname or "").endswith(".snowflake.app") or origin.port not in (None, 443):
            raise RuntimeError("Snowflake did not return a serverless service hostname")
        # Snowflake's SPCS tutorial documents this connector hook. Its interface is version-sensitive.
        transport = conn._rest
        if transport is None:
            raise RuntimeError("The Snowflake connection has no active session")
        result = transport._token_request("ISSUE")
        token = (result.get("data") or {}).get("sessionToken")
        if not token:
            raise RuntimeError("Snowflake did not issue a session token")
        headers = {"Authorization": f'Snowflake Token="{token}"', "Accept": "application/json"}

        def fetch(path, params):
            # A fresh HTTPS request to the discovered origin never follows a sign-in redirect.
            with closing(HTTPSConnection(origin.netloc, timeout=60)) as http:
                http.request("GET", path + "?" + urlencode(params), headers=headers)
                with http.getresponse() as response:
                    return page_json(
                        response.status,
                        response.getheader("Content-Type") or "",
                        response.read(),
                        response.getheader("Retry-After"),
                    )

        read_pages(fetch, args.table, args.limit, args.pages, args.cursor)


def from_browser(args):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=args.channel, headless=args.headless)
        context = browser.new_context(base_url=args.url)
        try:
            page = context.new_page()
            print("Complete Snowflake sign-in in the browser if prompted.", file=sys.stderr)
            page.goto(args.url + "/healthz", wait_until="commit", timeout=90000)
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                check = context.request.get("/healthz", max_redirects=0, timeout=60000)
                try:
                    if (
                        check.status == 200
                        and "application/json" in check.headers.get("content-type", "")
                        and check.json().get("status") == "ok"
                    ):
                        break
                    if check.status == 403:
                        raise RuntimeError("Snowflake denied access to this service")
                finally:
                    check.dispose()
                time.sleep(1)
            else:
                raise RuntimeError("Snowflake sign-in did not complete within three minutes")

            def fetch(path, params):
                response = context.request.get(path, params=params, max_redirects=0, timeout=60000)
                try:
                    return page_json(
                        response.status,
                        response.headers.get("content-type", ""),
                        response.body(),
                        response.headers.get("retry-after"),
                    )
                finally:
                    response.dispose()

            read_pages(fetch, args.table, args.limit, args.pages, args.cursor)
        finally:
            context.close()
            browser.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "url", nargs="?", type=service_origin, help="service origin for browser sign-in"
    )
    parser.add_argument("table", help="configured route name, e.g. demo")
    parser.add_argument("-c", "--connection", help="named Snowflake connection; discovers the URL")
    parser.add_argument(
        "--service", default="SNOWFASTAPI_DEV.API.SNOWFASTAPI", help="service for connection mode"
    )
    parser.add_argument("--role", help="Snowflake session role for connection mode")
    parser.add_argument("--limit", type=int, default=2)
    parser.add_argument("--pages", type=int, default=2)
    parser.add_argument("--cursor", help="resume this dataset using a preceding page's next_cursor")
    parser.add_argument("--channel", choices=["chromium", "chrome", "msedge"], default="chromium")
    parser.add_argument(
        "--headless", action="store_true", help="for an already accessible browser test origin"
    )
    args = parser.parse_args()
    if bool(args.connection) == bool(args.url):
        parser.error("Pass either -c CONNECTION or the URL before the table name")
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,62}", args.table) or min(args.limit, args.pages) < 1:
        parser.error("Supply a valid route name and positive limit and page count")
    if args.connection:
        from_connection(args)
    else:
        from_browser(args)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError) as error:
        sys.exit(str(error))
