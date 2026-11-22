# SnowFastAPI

Publish a Snowflake table as a read-only FastAPI endpoint by editing [tables.toml](tables.toml). Snowflake signs users in, enforces their data privileges and runs the Python service on serverless App Runtime. DCM manages the schema, demo table, seed view and supported grants.

The repository contains the [FastAPI application](app/), [DCM project](dcm/), [Python client](client.py), and [tests](tests/). Start with the [SnowFastAPI manual](docs/site/index.md) for the browser tutorial, deployment guides and API reference. Open the repository’s **Deployments → github-pages** entry for the rendered manual.

**Hosting requires a paid Snowflake account.** Python and serverless compute are in public preview. The Python client retrieved all five demo rows from a deployed service over HTTPS. [Verification results](docs/reviews/final-release.md) · [Snowflake availability](https://docs.snowflake.com/en/developer-guide/snowflake-app-runtime/limitations)

## Publish a table

After the [one-time account setup](docs/deployment.md), add an entry to `tables.toml` and deploy.

```toml
[tables.orders]
table = "ANALYTICS.SALES.ORDERS"
max_page_size = 100
```

```sh
uv run --group operator python manage.py deploy -c "$DEV_CONNECTION" \
  --metadata-role "$METADATA_ROLE" --grant-role "$GRANT_ROLE"
```

This creates `GET /v1/tables/orders`. The publisher discovers the table's declared primary key, checks the data, freezes the projected columns and generates its caller grants. Customer tables retain their existing ownership and user permissions. The role used to inspect the data needs read access and usage on the metadata warehouse.

| Setting | Behavior |
| --- | --- |
| `table` | Fully qualified Snowflake relation, or a name in this project's `API` schema. Standard names are uppercased. Double-quoted SQL identifiers preserve case. |
| `kind` | Defaults to `"table"`. Use `"view"` for a view so the administrator gets the correct grant. See the [hosted view verification](docs/verification.md#hosted-views) before choosing a view. |
| `max_page_size` | Defaults to 100. Accepts 1–1,000. Requests default to the smaller of 50 and this setting. |
| `columns` | Optional list of published columns in response order. Omitting it takes all visible columns at prepare time. A later release can add newly discovered columns. Use an explicit list or a curated view to control disclosures. |
| `key` | Optional ordered list of one to four columns. Tables default to their declared primary key. Views and keyless tables need an explicit key. Include each key in the published columns. |

For example, a view can publish only its order number and price.

```toml
[tables.prices]
table = "ANALYTICS.SALES.ORDER_PRICES"
kind = "view"
columns = ["ORDER_ID", "PRICE"]
key = ["ORDER_ID"]
max_page_size = 25
```

## Read pages

Use an existing named Snowflake connection to read the hosted demo. The client discovers the service URL from Snowflake, obtains a short-lived session credential and sends it only to that HTTPS origin. This mode uses the Python connector and requires no browser when the selected connection supports unattended sign-in.

```sh
uv run python client.py demo -c "$DEV_CONNECTION" --role SNOWFASTAPI_DEV_READER --limit 2 --pages 3
```

The client uses `--role` to discover and open the service. App Runtime executes the data query with the user's default role. Snowflake publishes the session-token mechanism in its SPCS tutorial and flags the connector hook as version-sensitive. This repository locks the version verified against the serverless gateway. Use `--service DB.SCHEMA.APP` for a different deployment. [Snowflake session-token example](https://docs.snowflake.com/en/developer-guide/snowpark-container-services/tutorials/advanced/tutorial-8-access-public-endpoint-programmatically#option-3-send-requests-to-the-service-endpoint-programmatically-by-using-a-session-token) · [Runtime role selection](https://docs.snowflake.com/en/developer-guide/snowflake-app-runtime/access-control)

For interactive sign-in, open the service URL. The root opens the OpenAPI contract at `/openapi.json`. Open `/docs` to try a data request in Swagger UI after Snowflake sign-in. The app serves the interface and its assets from the same origin. The client can also use an ephemeral browser session.

```sh
uv run --group client playwright install chromium
uv run --group client python client.py "$APP_URL" demo --limit 2 --pages 3
```

The browser client waits for Snowflake sign-in, prints one JSON object per page and closes its temporary session at exit. An installed Chrome or Edge can be selected with `--channel chrome` or `--channel msedge`. [Serverless ingress](https://docs.snowflake.com/en/developer-guide/snowflake-app-runtime/serverless) · [Browser request context](https://playwright.dev/python/docs/api/class-apirequestcontext)

Call `GET /v1/tables/demo?limit=2`. Each response contains `items` and `next_cursor`. Send the returned cursor as the next request's `cursor` query parameter. The final page has `next_cursor: null`. For example, the last demo page contains:

```json
{"items":[{"ID":5,"ITEM":"Eraser","PRICE":"0.65"}],"next_cursor":null}
```

The API uses ordered keyset queries with bound values. A cursor is an encoded row position, readable by its holder, and every page is authorized again. Use nonsensitive, immutable, unique, non-null keys that stay visible and unique under the caller's masking policy. Supported key types are scale-zero NUMBER, DATE and UTF-8 binary-ordered text up to 192 bytes per component. Keys and projections are checked at prepare time. The null and uniqueness scan can use substantial warehouse compute on a large table. Standard-table primary keys are informational. Concurrent inserts, deletes and key changes affect later pages. [Primary-key metadata](https://docs.snowflake.com/en/sql-reference/sql/show-primary-keys)

Snowflake column names are the JSON field names. Fixed-point decimals and integers outside JavaScript's safe range are strings. Dates and timestamps are ISO formatted, timestamps retain nanoseconds, and binary fields use base64. JSON-compatible semi-structured values become JSON. Snowflake-specific text such as an array containing a bare `undefined` is preserved as a string.

## Access and operating limits

- The gateway supplies a caller OAuth token. Each data request opens its own Snowflake connection and closes it after the query. Snowflake applies the caller's default role, row access and masking policies, bounded by the application's exact caller grants. Giving someone service access and giving them access to underlying customer data are separate administrator actions. [Caller rights](https://docs.snowflake.com/en/developer-guide/snowflake-app-runtime/query-snowflake) · [Sharing](https://docs.snowflake.com/en/developer-guide/snowflake-app-runtime/access-control)
- The service accepts four concurrent queries, caps item data per page at 4 MiB and sets a 30-second Snowflake statement timeout. Responses use `private, no-store`. Uvicorn access logs omit request URLs by disabling access logging. Queries carry the `SnowFastAPI` tag. The warehouse and serverless application compute are billed separately. [App Runtime cost](https://docs.snowflake.com/en/developer-guide/snowflake-app-runtime/cost)
- A bad cursor returns 400, missing caller context 401, denied data access 403, an unknown route 404, invalid key data 409, an oversized page 413, invalid limits 422 and saturation 429 with `Retry-After`. Warehouse timeouts return 504 and other database failures return 503. `/healthz` checks process readiness without a data query.

Run the offline tests with `uv run --locked --all-groups pytest -q`. This installs the Python dependencies and uses a mock browser. The [deployment guide](docs/deployment.md) covers the trial-compatible tests, administrator roles, scoped revocations and rollback.

## Build the manual

Edit the pages under `docs/site/`, then build and check the site from the repository root.

```sh
uvx --from zensical==0.1.3 zensical build --clean --strict
python3 scripts/check_site.py
```

## Existing clones

The project reissued its Git history with project attribution on November 21, 2026. If you cloned the repository before this rewrite, save any local work and start from a fresh clone. Transfer local edits as a patch onto the new history. Merging an old branch can restore obsolete attribution.
