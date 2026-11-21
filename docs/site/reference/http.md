# HTTP API

Use the HTTPS origin assigned to your Application Service. Snowflake authenticates access to that origin. An anonymous hosted request can receive a sign-in redirect before FastAPI sees it.

| Method and path | Result |
| --- | --- |
| `GET /` | Redirects to the OpenAPI JSON document. |
| `GET /openapi.json` | Machine-readable contract listing the routes in this release and each route's limit. |
| `GET /healthz` | Returns `{"status":"ok"}` when the Python process is ready. It does not query a warehouse. |
| `GET /docs` | FastAPI Swagger HTML. On the tested hosted service the gateway blocked its CDN assets. Use `/openapi.json` to inspect the live contract. |
| `GET /v1/tables/{name}` | Returns a page of rows for a configured dataset. A single database query serves each successful request. |

## Request parameters

| Parameter | Type | Behavior |
| --- | --- | --- |
| `name` | Path string | The dataset's TOML section name, such as `demo`. Only published routes exist. |
| `limit` | Optional integer | Minimum 1. Maximum is the configured `max_page_size`. Defaults to the smaller of 50 and the route maximum. |
| `cursor` | Optional string | At most 8,192 characters. Omit for page one. Pass the previous response's non-null value to continue on the same route. |

## Response

```json
{"items":[{"ID":5,"ITEM":"Eraser","PRICE":"0.65"}],"next_cursor":null}
```

`items` is an array of objects. Field names match the projected Snowflake column names. `next_cursor` is a string when more rows are available and JSON `null` at the end, including an empty result. An empty result returns HTTP 200. Pages use `Cache-Control: private, no-store`. See the [type mapping](types.md) for precision and representation.

## Status codes

| Status | Meaning |
| --- | --- |
| 200 | The operation succeeded. |
| 302 | The hosted gateway redirected an anonymous caller to Snowflake sign-in. |
| 307 | FastAPI redirects the service root to `/openapi.json` once authenticated. |
| 400 | Malformed cursor, wrong dataset or changed dataset definition. |
| 401 | Required caller identity is missing or Snowflake rejects an expired or invalid sign-in token. |
| 403 | Snowflake denied access or the published object is unavailable. |
| 404 | No matching path exists. |
| 409 | A row encountered while building the page violates the key contract. |
| 413 | Serialized item data for the page exceeds 4 MiB. Select fewer rows or narrower columns. |
| 422 | Request validation failed, including a limit outside the allowed range or an overlong cursor. |
| 429 | All four query slots in the process are busy. `Retry-After: 1` requests a one-second wait. |
| 500 | An unhandled application error occurred, including unsupported connector-native output values in this release. |
| 503 | A database failure could not be handled more specifically. |
| 504 | The Snowflake statement timed out. The service sets a 30-second statement timeout. |

The size limit applies to item data. It excludes the JSON envelope and cursor. Query slots and connections are per running process. See [Troubleshoot a request](../how-to/troubleshoot.md) for diagnosis.
