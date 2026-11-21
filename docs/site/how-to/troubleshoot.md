# Troubleshoot a request

Start with the exact URL path, HTTP status and whether Snowflake prompted for sign-in. An operator can correlate a data request with warehouse query history using the query tag `SnowFastAPI`.

| What you see | What to check |
| --- | --- |
| The browser redirects to Snowflake | Sign in at the service origin supplied by your operator. A 302 for an anonymous request is normal, including on `/healthz`. |
| Sign-in succeeds, but the data route returns 403 | Check service USAGE, the user's default-role data and warehouse privileges, and the execution role's exact caller grants. An unavailable published object can also produce 403. [Check access](access.md) |
| Only a view intermittently returns 403 | Check the precise `CALLER SELECT ON VIEW` grant and direct SELECT as the reader. DEV observed mixed results for a view with its documented grant. A standard table with a declared key passed repeated hosted checks. Save the failed query ID for your administrator. [Snowflake security](https://docs.snowflake.com/en/developer-guide/snowflake-app-runtime/security) |
| A cursor returns 400 | Start at page one of the same route and use the returned cursor unchanged. A configuration change can invalidate earlier cursors. |
| A request returns 422 | Supply an integer limit between 1 and the route maximum. Check that a cursor is within its length limit. |
| A page returns 409 or repeats unexpected rows | Check current key values and masking. A valid paging key must stay non-null, unique and visible for this reader. [Key requirements](../reference/configuration.md#pagination-keys) |
| The response is 413, 429 or 504 | Reduce the page size or projection on 413. On 429 wait for `Retry-After`. On 504 inspect query history and warehouse performance before retrying. |
| The data route returns 500 on a table with an interval | Publish an explicit projection with supported column types, or use a tested source representation. The current serializer cannot encode connector-native day-time intervals. [JSON types](../reference/types.md) |
| The interactive documentation page is blank | Open `/openapi.json` for the contract. The hosted gateway's content security policy blocked the default Swagger CDN assets in DEV. |
| Capabilities are true but the build fails on a trial | Hosting requires a paid account. The trial builder returned 395054 in DEV. After conversion the same account successfully hosted the service. [Snowflake trial conversion](https://docs.snowflake.com/en/user-guide/admin-trial-account#label-trial-account-convert) |
| Deployment reports an error after the URL is live | Inspect the active package version and pending caller-grant retirement before repeating the deployment. [Recover a release](releases.md#recover-a-failed-or-unwanted-release) |

For the complete list of statuses and response fields, use the [HTTP reference](../reference/http.md).
