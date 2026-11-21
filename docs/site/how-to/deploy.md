# Deploy the demo

Use this guide when you have the application checkout and can provision an isolated Snowflake environment. You will create a DCM project for the database objects and an Application Service for the Python process. The completed service exposes the five demo products.

## Prepare your environment

Use Python 3.13, uv, Snowflake CLI 3.30 or later and a working named connection. Hosting requires a paid account in a supported commercial region with Python serverless App Runtime enabled. Database queries and hosting can use credits. The examples use a POSIX shell and the DEV names from the checkout. [Snowflake availability](https://docs.snowflake.com/en/developer-guide/snowflake-app-runtime/limitations)

From the directory containing `manage.py`, set `DEV_CONNECTION` to your existing connection name. For a shared deployment, the [split deployment procedure](releases.md) lets a grant administrator and service owner perform their own steps.

```sh
export DEV_CONNECTION=my_dev_connection
export METADATA_ROLE=SNOWFASTAPI_DEV_READER
export GRANT_ROLE=ACCOUNTADMIN
snow connection test -c "$DEV_CONNECTION"
snow app setup --capabilities -c "$DEV_CONNECTION" --format json
```

Check that both `serverless` and `python-serverless` are true. The account must also meet the paid-account requirement. [App Runtime setup](https://docs.snowflake.com/en/developer-guide/snowflake-app-runtime/getting-started)

## Bootstrap the isolated database

The defaults use the database `SNOWFASTAPI_DEV`. To use different names, edit the DEV target and its matching configuration in `dcm/manifest.yml` before rendering the SQL. See the [deployment settings](../reference/configuration.md#deployment-settings).

```sh
mkdir -p build
uv run --frozen --group operator python manage.py bootstrap-sql > build/bootstrap.sql
cat build/bootstrap.sql
```

Read the generated SQL. Check the database, warehouse and three new role names against the environment you intend to provision. The administrator connection must be able to use `SECURITYADMIN`, `SYSADMIN` and the new project role. After reviewing the script, execute it once for this environment.

```sh
snow sql -c "$DEV_CONNECTION" -f build/bootstrap.sql
```

The script creates the project database, DCM schema, initially suspended X-Small warehouse and dedicated roles.

## Deploy the service

```sh
uv run --frozen --group operator python manage.py deploy -c "$DEV_CONNECTION" \
  --metadata-role "$METADATA_ROLE" --grant-role "$GRANT_ROLE"
```

Wait for the command to finish. It applies the DCM definitions, seeds five example rows, builds the Python package, grants service access to the reader and prints the HTTPS origin. Save the final origin. Preserve the deployment directory beneath `build/deployments/` for subsequent releases.

## Check the result

Give the intended reader the [demo reader role](access.md#give-a-reader-access). Open the printed origin in a browser. Snowflake prompts you to sign in and the root opens the OpenAPI JSON. Use the [browser tutorial](../tutorials/read-five-rows.md) to check the whole data path with a reader. A successful health request alone checks the process and leaves SQL permissions untested.

If the first deployment stops while Snowflake provisions a TLS certificate, follow the message and retry after issuance. Provisioning can take up to three hours. [Snowflake troubleshooting](https://docs.snowflake.com/en/developer-guide/snowflake-app-runtime/troubleshooting)
