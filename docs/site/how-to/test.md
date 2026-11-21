# Test a deployment

Run the checks from an implementation checkout. Choose the level that reaches the part of the system you changed.

## Run the offline suite

```sh
uv sync --frozen --all-groups
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync ty check app manage.py publishing.py client.py
uv run --no-sync pytest -q
```

The offline suite checks route limits, cursor handling, errors, generated SQL, metadata handling, release construction and client behavior. The three live tests are skipped unless you set their environment variables.

## Run the warehouse and hosted tests

Choose an isolated DEV environment with the demo bootstrap and deployed service. The connection's test role needs a warehouse and SELECT on `SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.REGION`. The DEV check also creates a session-scoped temporary table under the DCM role. Configure `DEV_CONNECTION` as in the [deployment guide](deploy.md).

```sh
uv run --frozen --group client playwright install chromium
SNOWFASTAPI_TEST_CONNECTION="$DEV_CONNECTION" \
  SNOWFASTAPI_TEST_DEV=1 SNOWFASTAPI_TEST_HOSTED=1 \
  uv run --frozen --group client pytest -q
```

Set `SNOWFASTAPI_TEST_ROLE` if the sample-data test needs a particular role. For an installed Chrome or Edge browser use `SNOWFASTAPI_TEST_BROWSER=chrome` or `msedge`. The hosted check uses the named connection and tests all three demo pages plus a rejected page size. If the account is a trial, omit `SNOWFASTAPI_TEST_HOSTED` and use the warehouse checks after preparing the DEV infrastructure. [Trial account limits](https://docs.snowflake.com/en/developer-guide/snowflake-app-runtime/getting-started)

## Compare two identities

Choose two existing test identities with different expected entitlements. Each needs a service share. Use a separate browser profile or named connection for each.

1. Record the expected rows and any masked values with a direct SELECT under each user's default role.
2. Read the same route as each user, including a second page. Compare rows and masked fields with that user's expected results.
3. For a user whose default role has no data access, expect a 403 on the data route even if sign-in succeeds. A user with an applicable row policy may instead get 200 and fewer rows.

Two role selections on one named connection still represent one identity. The DEV verification covered real hosting, authenticated pagination and direct role checks with one identity. Cross-user policy behavior needs the two-identity check in your environment.
