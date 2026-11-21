# Read pages with the Python client

Use the bundled client when you want JSON records in a terminal or script. Run the commands in the implementation checkout, in the directory containing `client.py`. You need Python 3.13, uv, a deployed route and a Snowflake identity with access to it.

## Use a named connection

Set `DEV_CONNECTION` to an existing connection name. The following command reads up to three pages of two products each. It stops early if it reaches the end.

```sh
export DEV_CONNECTION=my_dev_connection
uv run --frozen python client.py demo -c "$DEV_CONNECTION" \
  --role SNOWFASTAPI_DEV_READER --limit 2 --pages 3
```

The client discovers the service URL from Snowflake. It writes one JSON object per page to standard output. In the seeded demo the page lengths are 2, 2 and 1. The final row is Eraser. Redirect standard output to a file if you want to keep it.

The connection authenticates with its configured Snowflake method. The client obtains a short-lived credential in memory and sends it only to the HTTPS host returned by Snowflake. An unattended connection can run without a browser. The connector hook used here is version-sensitive, so use the checkout's lockfile. [Snowflake session-token example](https://docs.snowflake.com/en/developer-guide/snowpark-container-services/tutorials/advanced/tutorial-8-access-public-endpoint-programmatically)

For a different deployment, add `--service DB.SCHEMA.APP` using its three-part service name. The ingress role supplied by `--role` lets you discover and open the service. App Runtime uses the signed-in user's default role for the data query. [How request authorization works](../explanation/architecture.md#which-role-reads-the-data)

## Use browser sign-in

Set `APP_URL` to the HTTPS origin your operator gave you, without a path. Install the browser once, then run the client with the URL before the route name.

```sh
uv run --frozen --group client playwright install chromium
uv run --frozen --group client python client.py "$APP_URL" demo --limit 2 --pages 3
```

Complete Snowflake sign-in in the temporary browser window. The client waits up to three minutes during the sign-in polling phase, reads pages using that session and closes the browser. To use an installed browser, add `--channel chrome` or `--channel msedge`. For long paginated reads, use the named connection mode. The browser client retains response bodies until its context closes. [Client flags](../reference/commands.md#python-client)
