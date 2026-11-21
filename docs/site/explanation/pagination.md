# How pagination stays ordered

Suppose a reader requests two products. Snowflake sorts by the configured key and fetches up to three rows. The service returns the first two. Seeing a third row tells it to include a cursor for the position of the second. If it sees only two rows, the page is already complete.

With a single integer key, the next query asks for keys greater than the last returned ID. Values are bound separately from the SQL statement. With a composite key such as `(CUSTOMER_ID, ORDER_ID)`, the query first compares customers. Within the same customer it compares order IDs. The key order must match the declared or configured order across requests.

## What a cursor remembers

The cursor carries key values and a fingerprint of the route's dataset definition. The reader can inspect the encoded position, so use nonsensitive keys. Each request runs a new authorized query. Possessing a cursor supplies a position and confers no data privileges.

The cursor fits in the request URL and the server keeps no session state between pages. A cold start can therefore resume the same dataset. Changing the route definition can make an earlier cursor invalid. Start over at page one in that case.

## What can change between pages

The results are live. If a new row is inserted behind the reader's current position, the reader will miss it during this traversal. A later insert ahead of the cursor can appear on a subsequent page. Updating a key can move a row across that boundary. Deletions and policy changes can also change what remains visible.

Declare a unique, stable key and keep it visible under every reader's masking rules. The publisher scans current data because Snowflake standard tables typically declare a primary key without enforcing its uniqueness. Each page also checks the key values it encounters. A stable historical export requires its own stable source, such as a separately prepared immutable table. [Snowflake constraints](https://docs.snowflake.com/en/sql-reference/constraints-overview) · [Key configuration](../reference/configuration.md#pagination-keys)
