# Publish a table

Use this guide to add a read-only route to an existing deployment. You need the implementation checkout, a role that can inspect and read the source, and a grant administrator for the new caller grants. Readers need ordinary access to the source as well.

## Name the dataset

Open `tables.toml`. For a table with a declared primary key, add a section like this. Replace the example relation with your own.

```toml
[tables.orders]
table = "ANALYTICS.SALES.ORDERS"
max_page_size = 100
```

The section name becomes `/v1/tables/orders`. The publisher reads the declared primary key in order and checks the current data for nulls and duplicate keys. On a large table, this scan can consume warehouse time. Use an immutable, nonsensitive key that stays unique and visible for every intended reader.

## Choose which columns to publish

If you omit `columns`, the release captures all columns visible during preparation. To keep newly added source columns out of future releases until you approve them, specify a projection. Include every pagination key.

```toml
[tables.orders]
table = "ANALYTICS.SALES.ORDERS"
columns = ["ORDER_ID", "ORDER_DATE", "TOTAL"]
key = ["ORDER_ID"]
max_page_size = 100
```

A keyless table needs an explicit `key`. A view also needs `kind = "view"` and an explicit key. In DEV, a hosted view intermittently returned 403 despite its documented caller grant. Test your view under the intended reader before sharing it. The [configuration reference](../reference/configuration.md) lists identifier and key restrictions.

## Prepare, publish and check

Use a dedicated metadata login with only the privileges the publisher needs. The current preparation code selects a primary role and retains the connection's configured secondary roles. Check the [access guide](access.md#verify-the-metadata-identity) if your operator login holds several roles.

For staged review, [prepare the release and inspect its catalog diff](releases.md). To run all steps with your selected operator roles, use the deployment command below from the checkout.

```sh
uv run --frozen --group operator python manage.py deploy -c "$DEV_CONNECTION" \
  --metadata-role "$METADATA_ROLE" --grant-role "$GRANT_ROLE"
```

Sign in as a reader and open `/v1/tables/orders?limit=2`. Check the names returned in `items` and follow the cursor once. When access policies differ among readers, [compare two Snowflake identities](test.md#compare-two-identities).
