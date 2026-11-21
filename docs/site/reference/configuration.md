# Dataset configuration

`tables.toml` is the input to `prepare` and `deploy`. Each section under `tables` defines one GET route. At least one dataset is required. Unknown fields fail validation.

```toml
[tables.orders]
table = "ANALYTICS.SALES.ORDERS"
max_page_size = 100
```

## Dataset fields

| Field | Required | Accepted values and default |
| --- | --- | --- |
| Section name | Yes | A lowercase ASCII letter followed by up to 62 lowercase letters, digits, underscores or hyphens. `[tables.orders]` maps to `/v1/tables/orders`. |
| `table` | Yes | A Snowflake relation name. Supply a single name in the deployment's `API` schema or exactly three parts, `DB.SCHEMA.OBJECT`. |
| `kind` | No | `"table"` by default. Use `"view"` for a view. The value selects the object kind for metadata and caller grants. |
| `columns` | No | Nonempty list of distinct published column names, in response order. Omitting it snapshots all columns visible at preparation. Every key must be in the projection. |
| `key` | Conditional | Ordered list of one to four distinct column names. Omit to discover a table's declared primary key. Supply it for a keyless table or view. |
| `max_page_size` | No | Integer from 1 through 1,000, default 100. The HTTP request default is the smaller of 50 and this limit. The shipped demo sets 50. |

A new release can expose newly visible columns when you omit `columns`. Use an explicit projection for a stable public contract. The catalog records projected names, SQL types, key order and the maximum page size. A change to any of these can invalidate a cursor.

## Identifier spelling

Unquoted identifiers are folded to uppercase. Double-quoted identifiers preserve exact spelling. Use TOML literal strings when a Snowflake name contains quotes. The following example describes a relation whose schema is `Sales Ops` and whose column is `Order ID`.

```toml
[tables.special_orders]
table = 'ANALYTICS."Sales Ops"."Orders"'
columns = ['"Order ID"', 'TOTAL']
key = ['"Order ID"']
```

Names can contain embedded periods inside quoted parts. Use two double quotes for an embedded double quote inside a quoted Snowflake identifier. Identifiers must be printable and at most 255 characters.

## Pagination keys

| Snowflake type | Ordering and constraints |
| --- | --- |
| `NUMBER(p,0)` | Exact integer comparison, up to 38 digits. Scale must be zero. |
| `DATE` | Calendar date. Cursor values use `YYYY-MM-DD`. |
| Text | Ordered under Snowflake's `utf8` collation. Each key component must fit in 192 UTF-8 bytes. Case-distinct strings can occupy separate positions. |

Preparation scans current keys for nulls, duplicates and overlong text. Standard-table primary keys are generally informational. Keep keys immutable and unique under the masking and row policies that apply to each reader. Choose nonsensitive keys because the encoded cursor is readable. [Snowflake constraint behavior](https://docs.snowflake.com/en/sql-reference/constraints-overview)

## Deployment settings

The DEV defaults live in `dcm/manifest.yml`. The default target selects its templating configuration. Deployment names use uppercase letters, digits and underscores, starting with a letter or underscore.

| Setting | DEV default | Use |
| --- | --- | --- |
| Target `project_name` | `SNOWFASTAPI_DEV.DCM.SNOWFASTAPI` | Must match the configured database plus `.DCM.SNOWFASTAPI`. |
| Target `project_owner` | `SNOWFASTAPI_DEV_DCM` | DCM role. |
| Target `account_identifier` | Omitted | Optional organization-account guard for the Snowflake CLI DCM target. |
| `database_name` | `SNOWFASTAPI_DEV` | Contains the project and API schemas. |
| `warehouse_name` | `SNOWFASTAPI_DEV_WH` | Warehouse used for data queries and default metadata preparation. |
| `app_owner` | `SNOWFASTAPI_DEV_OWNER` | Owns the Application Service and receives restricted caller grants. |
| `reader_role` | `SNOWFASTAPI_DEV_READER` | Receives service USAGE and ordinary reads on the sample table. |

The service name is `<database_name>.API.SNOWFASTAPI`. The app manifest sets Python, serverless compute and `/healthz` for readiness. See [deployment commands](commands.md#deployment-commands).
