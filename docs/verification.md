# Verification

The initial checks used Snowflake CLI 3.34.0, Python 3.13.16 and the Python connector 4.8.1. Snowflake built and served the application in an isolated DEV environment.

| Check | Observed result |
| --- | --- |
| Hosted service | `DESCRIBE APPLICATION SERVICE SNOWFASTAPI_DEV.API.SNOWFASTAPI` returned `RUNNING`, `SERVERLESS`, minimum instances 0, auto-suspend 3,600 seconds and an HTTPS URL. The X-Small query warehouse has 60-second auto-suspend. |
| Sign-in and HTTP | Anonymous health and data requests received 302 redirects to the account's Snowflake sign-in. Edge displayed the sign-in prompt. A credential issued through the named connection retrieved the health response, OpenAPI contract and demo rows. A malformed cursor returned 400, an unknown route 404 and a limit of 51 returned 422. |
| Hosted pagination | Four fresh named-connection sessions each retrieved IDs 1–5 over HTTPS in pages of 2, 2 and 1. Each final page returned a null cursor. The hosted pytest check independently exercised the same flow. |
| DCM and data | DCM created the API schema, sample relations and scoped grants. The repeatable seed inserted five rows on its first run and zero on a second run. The full postdeployment DCM plan reported zero changes. |
| Reader and owner | With secondary roles disabled, the reader retrieved demo IDs 1–5. Ordinary SELECT on the same table was denied to the application owner. The owner had four caller grants covering the database, schema, warehouse and demo table. The previous view caller grant was revoked. |
| Configuration-only onboarding | A session-scoped standard Snowflake table with a two-column primary key took only a table name and max page size. The publisher discovered the ordered key. Two pages returned the four expected rows, including case-distinct text keys and a 38-digit integer. |
| Python client and SQL | The Python client drove a headless Chrome session against a loopback FastAPI server connected to Snowflake. It retrieved all five TPC-H region keys in pages of 2, 2 and 1. This test supplied the gateway identity in its local fixture. |
| Serialization | An actual Snowflake query returned a sparse array, a string VARIANT and a nanosecond timestamp. The serializer preserved the Snowflake-only array representation and all nine timestamp fractional digits. |
| Packaging | The release contained eight files. Snowflake CLI validated the manifest. The pinned pip install completed in an isolated Python 3.13 environment, the production entry point returned HTTP 200 for readiness, the OpenAPI contract listed the demo route and an anonymous data call returned 401. A Linux x86-64 wheel resolution also succeeded. |
| Automated checks | All 38 tests passed with the live checks enabled. This includes the hosted client, a real warehouse queried through a loopback API, and a role/metadata test against DEV. The offline run passed 35 tests and skipped the three live checks. Ruff lint, formatting, type checks and the lockfile-to-requirements comparison passed locally. |
| Before the upgrade | Both serverless capability flags were true on trial. The manifest validated and eight files uploaded, then the remote builder refused the trial account with error 395054. The same account hosted the service after conversion to paid. |

The service role used to open a connection and the role recorded for a hosted data query can differ. Reader-role and owner-role ingress sessions belonged to one Snowflake identity. Query history recorded its default role for both sets of data requests. The programmatic client completed authenticated requests. See the final release review for the follow-up with two identities. [Snowflake role selection](https://docs.snowflake.com/en/developer-guide/snowflake-app-runtime/access-control)

The [additional implementation review](reviews/implementation.md) repeated all 38 tests and verified limitations in metadata role selection, grant retirement, interval serialization, the hosted Swagger UI and browser-client memory use.

See the [final release review](reviews/final-release.md) for the corrected package, a second Snowflake identity, and the final documentation and privacy checks.

## Hosted views

The first release published a view. Its reader could select all rows directly, and the service owner had an explicit `GRANT CALLER SELECT ON VIEW`. Repeated hosted requests using the same identity, role and SQL produced both successful pages and 403 responses. Failed statements recorded Snowflake error 2003. The cause remains unconfirmed. Snowflake documents this view grant. The default demo now uses a standard table with a declared primary key, which passed the repeated hosted checks. Verify a view in your own account before relying on it. [App Runtime security](https://docs.snowflake.com/en/developer-guide/snowflake-app-runtime/security#scoping-callers-rights)

For repeatable checks, see the [deployment guide](deployment.md#test-the-hosted-service). The [design record](design.md) describes the two peer reviews. Snowflake documents the paid-account requirement and how to upgrade a trial. [App Runtime requirements](https://docs.snowflake.com/en/developer-guide/snowflake-app-runtime/getting-started) · [Trial conversion](https://docs.snowflake.com/en/user-guide/admin-trial-account#label-trial-account-convert)
