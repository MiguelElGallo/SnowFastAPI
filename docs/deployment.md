# Deploy SnowFastAPI

The [operator manual](site/how-to/deploy.md) includes the browser tutorial, separate-role release procedure, grant requirements and recovery checks.

Use Python 3.13, uv, Snowflake CLI 3.30 or newer, and a named Snowflake connection. The connection's user needs access to the roles used in each step. Use a paid commercial-region account with Python and serverless enabled to host the application. The sample uses an isolated standard database named `SNOWFASTAPI_DEV` so the service can be shared.

## Set up the environment once

1. Choose a dedicated database and new role names. The DEV defaults are in [the DCM manifest](../dcm/manifest.yml). To change the database, update both the target project name and the database variable. Set the optional `account_identifier` to your organization's account identifier to enable the Snowflake CLI's account check.
2. Set the CLI connection and administrative roles for your environment. The disposable demo works with the built-in administrator role for applying grants. In a shared environment, an administrator can run the grant files separately.
3. Render and inspect the bootstrap SQL, then execute it with the authorized administrator connection.

```sh
export DEV_CONNECTION=my_snowflake_dev_connection
export METADATA_ROLE=SNOWFASTAPI_DEV_READER
export GRANT_ROLE=ACCOUNTADMIN
mkdir -p build
uv run --group operator python manage.py bootstrap-sql -c "$DEV_CONNECTION" > build/bootstrap.sql
cat build/bootstrap.sql
```

Check the organization-account identifier in the rendered account guard, the database, the warehouse and the three distinct role names. Execute the script with the same connection. The guard runs before any DDL.

```sh
snow sql -c "$DEV_CONNECTION" --enable-templating NONE -f build/bootstrap.sql
```

Bootstrap creates the dedicated roles, a database, DCM schema, DCM project and an initially suspended X-Small warehouse with 60-second auto-suspend. It attaches the roles to SYSADMIN. Grant a reader role to intended users through your existing role hierarchy. DCM grants the reader ordinary SELECT on the demo table. For a customer table, choose an existing appropriately scoped metadata role with SELECT and warehouse usage. Configure `--metadata-warehouse` if it uses a different warehouse.

| Responsibility | Default role | Required access |
| --- | --- | --- |
| DCM infrastructure | `SNOWFASTAPI_DEV_DCM` | Owns the DCM project. Can create the API schema, run plans and upload definitions to a temporary stage. |
| Build and service ownership | `SNOWFASTAPI_DEV_OWNER` | Uses the query warehouse. Creates the stage, build service, artifact repository and application in the isolated schema. Needs endpoint binding. |
| Caller grant administration | Administrator selected by the operator | Needs MANAGE CALLER GRANTS and a privilege on each referenced object. The combined command also applies the schema and account deployment grants. |
| Read data | User's default role | Needs ordinary USAGE on the source database, schema and query warehouse, and SELECT on the source relation. Opening the app also requires USAGE on the app and its containing database/schema. |

The publisher creates exact caller grants for the execution role. These authorize it to use a caller's existing privileges. They do not give the owner ordinary SELECT. [GRANT CALLER](https://docs.snowflake.com/en/sql-reference/sql/grant-caller) · [App Runtime privileges](https://docs.snowflake.com/en/developer-guide/snowflake-app-runtime/privileges)

## Deploy

```sh
snow app setup -c "$DEV_CONNECTION" --capabilities --format json
uv run --group operator python manage.py deploy -c "$DEV_CONNECTION" \
  --metadata-role "$METADATA_ROLE" --grant-role "$GRANT_ROLE"
```

The command compares the account returned by the CLI and the Python connector, runs a full DCM plan and deploy, seeds missing demo IDs and compiles the catalog with secondary roles disabled. It applies the grants, builds a new version, and waits for its exact repository, package and immutable version to be running. The new release directory contains `published-artifact.json`. It shares the service with the current reader, retires obsolete grants and writes the success receipt. Use the split flow when an operator must test a changed route before retirement.

The warehouse handles data queries. Serverless compute hosts the Python process and stops after an hour without requests at the default setting. The next request wakes the app. The first eligible account deployment can pause while Snowflake issues its TLS certificate, which can take up to three hours. Retry after issuance. [Serverless idle timeout](https://docs.snowflake.com/en/developer-guide/snowflake-app-runtime/scale-and-suspend) · [Troubleshooting](https://docs.snowflake.com/en/developer-guide/snowflake-app-runtime/troubleshooting)

Releases and the last successful catalog are stored under `build/deployments/<account>/<service>/`. Preserve these artifacts between CI jobs and serialize publishes targeting the same service. On a new checkout pass `--previous /path/to/last-successful/catalog.json` so the publisher can calculate revocations. A failed build can leave the stage, repository and prepared role grants in Snowflake. Retry the same release intent or compare `SHOW CALLER GRANTS TO ROLE SNOWFASTAPI_DEV_OWNER` against the last successful catalog and retire any caller grants added solely for the abandoned release. The success receipt is written after sharing and grant retirement complete.

## Split administrator and publisher duties

Run the following from the repository root. The preparation directory must be new. For subsequent releases pass the prior catalog with `--previous`.

```sh
uv run --group operator python manage.py plan -c "$DEV_CONNECTION"
uv run --group operator python manage.py apply-infra -c "$DEV_CONNECTION"
uv run --group operator python manage.py prepare -c "$DEV_CONNECTION" \
  --metadata-role "$METADATA_ROLE" --output build/release-1
```

Review `build/release-1/catalog.diff`. An administrator applies `publisher-grants.sql` and `caller-grants.sql`. The service owner publishes and applies `share.sql`. After validating the new release, the caller-grant administrator applies a nonempty `retire-caller-grants.sql`. The administrator for ordinary database and warehouse grants applies a nonempty `retire-reader-grants.sql`.

```sh
snow sql -c "$DEV_CONNECTION" --role "$GRANT_ROLE" --enable-templating NONE -f build/release-1/publisher-grants.sql
snow sql -c "$DEV_CONNECTION" --role "$GRANT_ROLE" --enable-templating NONE -f build/release-1/caller-grants.sql
uv run --group operator python manage.py publish -c "$DEV_CONNECTION" --release build/release-1
snow sql -c "$DEV_CONNECTION" --role SNOWFASTAPI_DEV_OWNER --enable-templating NONE -f build/release-1/share.sql
```

Keep the catalog of the version actually published for the next release. To roll back, restore the earlier caller grants, DCM access settings, reader service share, and database and warehouse grants. Select its immutable package version, verify the endpoint as that reader, and retire privileges specific to the abandoned release. [Snowflake package rollback](https://docs.snowflake.com/en/developer-guide/snowflake-app-runtime/deploy#label-snowflake-app-runtime-deploy-rollback)

## Test on a trial

The infrastructure, metadata preparation and local client/warehouse checks work independently of hosted compute. The normal test suite skips warehouse checks until you select a connection. The first live check needs a role with read access to the five-row Snowflake sample REGION table and a warehouse configured on the connection. The optional DEV check uses the bootstrapped roles and a session-scoped temporary table to verify composite primary-key discovery.

```sh
uv sync --frozen --all-groups
uv run --group client playwright install chromium
SNOWFASTAPI_TEST_CONNECTION="$DEV_CONNECTION" SNOWFASTAPI_TEST_DEV=1 \
  uv run --group client pytest -q
```

## Test the hosted service

After deployment, run the client with the reader role. It resolves the service URL and prints a JSON object per page. Use a user whose default role can read the demo table.

```sh
uv run python client.py demo -c "$DEV_CONNECTION" --role SNOWFASTAPI_DEV_READER --limit 2 --pages 3
SNOWFASTAPI_TEST_CONNECTION="$DEV_CONNECTION" SNOWFASTAPI_TEST_DEV=1 SNOWFASTAPI_TEST_HOSTED=1 \
  uv run --group client pytest -q
```

The hosted smoke test checks the row IDs, final cursor and rejection of a limit above 50. To validate your own data policies, run the client under two existing Snowflake identities whose default roles have different row or column entitlements. Compare their results with the same SELECT executed directly as each user.
