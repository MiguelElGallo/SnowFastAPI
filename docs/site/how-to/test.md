# Test a deployment

Run the checks from an implementation checkout. Choose the level that reaches the part of the system you changed.

## Run the offline suite

```sh
uv sync --locked --all-groups
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync ty check app manage.py publishing.py client.py
uv run --no-sync pytest -q
```

The offline suite checks route limits, cursor handling, errors, generated SQL, metadata handling, release construction and client behavior. Set the connection to enable the warehouse smoke test. The isolated DEV and hosted checks each require the literal value `1` for their opt-in flag.

## Run the warehouse and hosted tests

Choose an isolated DEV environment with the demo bootstrap and deployed service. The connection's test role needs a warehouse and SELECT on `SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.REGION`. The DEV check also creates a session-scoped temporary table under the DCM role. Configure `DEV_CONNECTION` as in the [deployment guide](deploy.md).

```sh
uv run --frozen --group client playwright install chromium
SNOWFASTAPI_TEST_CONNECTION="$DEV_CONNECTION" \
  SNOWFASTAPI_TEST_DEV=1 SNOWFASTAPI_TEST_HOSTED=1 \
  uv run --locked --all-groups pytest -q
```

Set `SNOWFASTAPI_TEST_ROLE` if the sample-data test needs a particular role. For an installed Chrome or Edge browser use `SNOWFASTAPI_TEST_BROWSER=chrome` or `msedge`. The hosted check uses the named connection, reads the maximum page size from the live OpenAPI contract, resumes with a fresh session, and tests both the maximum and one row above it. The DEV tests also check the JSON representation of real Snowflake intervals and a numeric-key MAP. If the account is a trial, omit `SNOWFASTAPI_TEST_HOSTED` and use the warehouse checks after preparing the DEV infrastructure. [Trial account limits](https://docs.snowflake.com/en/developer-guide/snowflake-app-runtime/getting-started)

## Compare two identities

Choose two existing test identities with different expected entitlements. Each needs a service share. Use a separate browser profile or named connection for each.

1. In a direct SQL session for each user, select that user's default role, run `USE SECONDARY ROLES NONE`, and record `CURRENT_ROLE()` and `CURRENT_SECONDARY_ROLES()`. Record expected rows and masked values with a SELECT ordered by the published key. Compare by key if the SQL client's display order differs.
2. Read the same route as each user, including a second page. Compare rows and masked fields with that user's expected results.
3. For a user whose default role has no data access, expect a 403 on the data route even if sign-in succeeds. A user with an applicable row policy may instead get 200 and fewer rows.

Two role selections on one connection use the same Snowflake user. Verify table access with distinct identities. To verify a masking or row access policy, use identities with known policy results and compare their values and row keys across pages.

In the DEV demo, a second Snowflake identity could open the service and read its health response. The data route returned 403 before that identity received table SELECT, returned all five expected rows after the grant, and returned 403 again after revocation. The direct SQL results matched all three phases. That check covers ordinary table access. Row access and masking policies need their own expected results.
