import os
from contextlib import closing
from threading import BoundedSemaphore
from typing import Annotated, Any

import snowflake.connector
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, JsonValue
from snowflake.connector.errors import Error

from .catalog import Catalog, Dataset
from .paging import (
    MAX_CURSOR,
    BadCursor,
    DataContractError,
    PageTooLarge,
    decode_cursor,
    make_page,
    page_query,
)


class Page(BaseModel):
    items: list[dict[str, JsonValue]]
    next_cursor: str | None


class ErrorResponse(BaseModel):
    detail: str


PRIVATE_HEADERS = {"Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer"}
PAGE_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse, "description": description}
    for code, description in {
        400: "Invalid cursor for this dataset.",
        401: "The Snowflake caller identity is missing, expired or rejected.",
        403: "Access was denied or the published object is unavailable.",
        409: "A returned row violates the published pagination key.",
        413: "The page exceeds the serialized item size limit.",
        422: "A query parameter failed validation.",
        429: "All query slots are busy.",
        500: "An unexpected application error occurred.",
        503: "Snowflake could not serve this page.",
        504: "The Snowflake query was canceled or exceeded its timeout.",
    }.items()
}
PAGE_ERRORS[429]["headers"] = {
    "Retry-After": {
        "description": "Seconds to wait before retrying.",
        "schema": {"type": "integer"},
    }
}


def connect_caller(token: str, warehouse: str):
    return snowflake.connector.connect(
        host=os.environ["SNOWFLAKE_HOST"],
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        warehouse=warehouse,
        authenticator="oauth",
        token=token,
        paramstyle="qmark",
        login_timeout=10,
        network_timeout=30,
        session_parameters={"STATEMENT_TIMEOUT_IN_SECONDS": 30, "QUERY_TAG": "SnowFastAPI"},
    )


def database_error(error: Error) -> HTTPException:
    if error.sqlstate == "42501" or error.errno in {2003, 2043, 3001}:
        return HTTPException(403, "Snowflake denied access or the published object is unavailable")
    if error.errno in {390303, 390318, 390144} or error.sqlstate == "28000":
        return HTTPException(401, "Snowflake sign-in expired or was rejected")
    if error.errno == 630:
        return HTTPException(504, "Snowflake query timed out")
    if error.errno == 604 or error.sqlstate == "57014":
        return HTTPException(504, "Snowflake query was canceled or timed out")
    return HTTPException(503, "Snowflake could not serve this page")


def create_app(catalog: Catalog, connect=connect_caller) -> FastAPI:
    slots = BoundedSemaphore(4)
    app = FastAPI(
        title="SnowFastAPI",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        description=(
            "Sign in at the Snowflake service URL to try a data route here. "
            "The Snowflake gateway authenticates the browser session or the named-connection "
            "client's Snowflake session token and supplies the caller identity to the service. "
            "Snowflake checks your data privileges for every page."
        ),
    )

    @app.middleware("http")
    async def private_responses(request, call_next):
        response = await call_next(request)
        response.headers.update(PRIVATE_HEADERS)
        return response

    @app.exception_handler(Exception)
    async def unexpected_error(request, error):
        return JSONResponse(
            {"detail": "The service could not complete this request."},
            status_code=500,
            headers=PRIVATE_HEADERS,
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request, error):
        return JSONResponse(
            {"detail": "Invalid query parameter. See this route's limits."}, status_code=422
        )

    @app.get("/healthz", include_in_schema=False)
    def health():
        return {"status": "ok"}

    @app.get("/", include_in_schema=False)
    def index():
        return RedirectResponse("/openapi.json")

    app.mount(
        "/docs/assets",
        StaticFiles(packages=[("fastapi_swagger", "resources")]),
        name="swagger-assets",
    )

    @app.get("/docs", include_in_schema=False, response_class=HTMLResponse)
    def swagger():
        return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SnowFastAPI · Swagger UI</title>
  <link rel="icon" href="/docs/assets/favicon-32x32.png">
  <link rel="stylesheet" href="/docs/assets/swagger-ui.css">
  <script defer src="/docs/assets/swagger-ui-bundle.js"></script>
  <script defer src="/docs/initialize.js"></script>
</head>
<body><div id="swagger-ui"></div></body>
</html>"""

    @app.get("/docs/initialize.js", include_in_schema=False)
    def initialize_swagger():
        # Load only from the service origin, including the initialization script.
        return Response(
            'SwaggerUIBundle({url: "/openapi.json", dom_id: "#swagger-ui", '
            "deepLinking: true, validatorUrl: null});",
            media_type="application/javascript",
        )

    def endpoint(name: str, dataset: Dataset):
        fingerprint = dataset.fingerprint(name)

        def list_rows(
            request: Request,
            limit: Annotated[int, Query(ge=1, le=dataset.max_page_size)] = min(
                50, dataset.max_page_size
            ),
            cursor: Annotated[str | None, Query(max_length=MAX_CURSOR)] = None,
        ) -> Page:
            tokens = request.headers.getlist("sf-context-current-user-token")
            if len(tokens) != 1 or not tokens[0].strip():
                raise HTTPException(401, "Sign in through the Snowflake application URL")
            try:
                after = (
                    None
                    if cursor is None
                    else decode_cursor(cursor, fingerprint, dataset.key_columns)
                )
                sql, binds = page_query(dataset, after, limit)
                if not slots.acquire(blocking=False):
                    raise HTTPException(
                        429, "All query slots are busy", headers={"Retry-After": "1"}
                    )
                try:
                    with closing(connect(tokens[0], catalog.warehouse)) as connection:
                        with closing(connection.cursor()) as db:
                            db.execute(sql, binds)
                            return Page(**make_page(dataset, fingerprint, db, limit))
                finally:
                    slots.release()
            except BadCursor:
                raise HTTPException(
                    400, "Invalid cursor for this dataset. Restart at page one."
                ) from None
            except DataContractError:
                raise HTTPException(
                    409, "The data no longer satisfies its published pagination key"
                ) from None
            except PageTooLarge:
                raise HTTPException(
                    413, "Use a smaller limit or a narrower published projection"
                ) from None
            except Error as error:
                raise database_error(error) from None

        return list_rows

    for name, dataset in catalog.tables.items():
        app.add_api_route(
            f"/v1/tables/{name}",
            endpoint(name, dataset),
            methods=["GET"],
            response_model=Page,
            responses=PAGE_ERRORS,
            openapi_extra={
                "x-snowflake-authentication": {
                    "enforcedBy": "Snowflake App Runtime gateway",
                    "methods": ["Snowflake browser session", "Snowflake session token"],
                }
            },
            operation_id=f"list_{name}",
            summary=f"List {name}",
            description="Published columns: " + ", ".join(c.name for c in dataset.columns),
        )
    return app
