# Design and review record

## Initial plan and research

Serve a versioned, read-only FastAPI endpoint per configured dataset. Start with the upstream template's Pydantic response models, dependency injection, OpenAPI and pytest patterns. Give Snowflake responsibility for sign-in, row access, masking and deployment. Use bounded keyset pages and a Python client that follows the returned cursor. [FastAPI reference implementation](https://github.com/fastapi/full-stack-fastapi-template/tree/master/backend) · [Snowflake announcement, November 19, 2026](https://www.snowflake.com/en/blog/snowflake-app-runtime/)

Snowflake introduced Python 3.13 and serverless compute in public preview. Each service currently has a single instance and scales to zero. SQL still runs on a warehouse. Use a standard database so the service can be shared. [Serverless compute](https://docs.snowflake.com/en/developer-guide/snowflake-app-runtime/serverless) · [Python runtime](https://docs.snowflake.com/en/developer-guide/snowflake-app-runtime/build-python-app)

## First independent review

The reviewer identified three changes to the proposed deployment and authentication design.

1. DCM can own the schema, demo view and supported grants. Snowflake CLI must build and publish the Application Service separately. DCM explicitly excludes caller grants. [Supported entities](https://docs.snowflake.com/en/user-guide/dcm-projects/dcm-projects-supported-entities)
2. Use the initiating user's complete OAuth token from the serverless gateway for every data connection. Give the service a dedicated creator role and explicitly select the query warehouse in Python. [Query from Python](https://docs.snowflake.com/en/developer-guide/snowflake-app-runtime/query-snowflake)
3. Use Snowflake's browser sign-in for the test client. The PAT and session-token recipes we found cover SPCS. The published serverless gateway contract describes authenticated HTTPS on the account's `snowflake.app` domain. We found no documented general unattended HTTP authentication flow for this gateway. [Serverless ingress](https://docs.snowflake.com/en/developer-guide/snowflake-app-runtime/serverless) · [SPCS client tutorial](https://docs.snowflake.com/en/developer-guide/snowpark-container-services/tutorials/advanced/tutorial-8-access-public-endpoint-programmatically)

## Follow-up research

A browser's Playwright request context shares its signed-in cookie jar. This lets a Python client issue HTTPS requests through the same Snowflake session and discard it when the browser closes. The service receives a new caller context on each request. A user's default role governs the data query even when another role supplies service access. [Playwright](https://playwright.dev/python/docs/api/class-apirequestcontext) · [Snowflake access control](https://docs.snowflake.com/en/developer-guide/snowflake-app-runtime/access-control)

Snowflake reports ordered primary-key metadata. Standard tables typically declare uniqueness without enforcing it. A view can report a nullable column even if its actual values form a valid key. Read column names at release time and check the actual keys for nulls and duplicates. [SHOW PRIMARY KEYS](https://docs.snowflake.com/en/sql-reference/sql/show-primary-keys) · [Snowflake constraints](https://docs.snowflake.com/en/sql-reference/constraints-overview) · [DESCRIBE TABLE](https://docs.snowflake.com/en/sql-reference/sql/desc-table)

## Second independent review and implementation plan

1. Bootstrap a dedicated DCM project location, warehouse and roles. Use DCM for the app schema and deterministic example data. Use one config entry per table, with optional projection, key and page size. Keep customer tables under their existing ownership.
2. Prepare a release from Snowflake metadata. Freeze the approved output names, show changes when preparing again, infer ordered table keys, and require explicit keys for views or keyless tables. Use exact integers, dates or binary-ordered text for pagination. Fail clearly on unsupported keys. Operators must select immutable, nonsensitive keys that stay unique and visible under every applicable policy.
3. Generate narrowly scoped caller privileges and reviewable revocations for removed objects. The grant administrator needs both `MANAGE CALLER GRANTS` and access to each referenced object. Preserve each user's existing data entitlements. [GRANT CALLER](https://docs.snowflake.com/en/sql-reference/sql/grant-caller)
4. Read data using one caller connection per page. Select explicit identifiers, bind cursor values and fetch one extra row. Treat a cursor as a user-supplied position, tied to its route and schema. Keep it usable across cold starts. Use a database-independent readiness route, private cache controls and access logging that omits URLs.
5. Package the runtime and compiled catalog, validate both deployment phases and run the Python client. Exercise pagination, cursor errors, projections, access failures and cold starts locally. Record which checks reach a real Snowflake warehouse and which reach a hosted App Runtime service.

## Hosted evidence and final client design

After the account upgraded, the serverless gateway accepted a short-lived session credential issued through the named Snowflake connection. Using the reader role, the Python client discovered the URL with DESCRIBE APPLICATION SERVICE and retrieved all three pages of the live demo. That result justified adding connection-based access as the primary test-client path. The implementation uses the connector hook in Snowflake's SPCS tutorial, which Snowflake identifies as version-sensitive. Browser sign-in remains available. [Documented session-token mechanism](https://docs.snowflake.com/en/developer-guide/snowpark-container-services/tutorials/advanced/tutorial-8-access-public-endpoint-programmatically) · [Verification](verification.md)

During repeat runs the hosted view intermittently returned 403 despite its documented caller grant. An independent review checked Snowflake's view-grant syntax and role-selection rules. We changed the default demo to a standard table with a declared primary key so that it also exercises table-only configuration. DCM owns the sample relations. A postdeployment MERGE seeds missing IDs. The next release retired the old view's caller grant. Four fresh sessions paged through the table successfully. [App Runtime security](https://docs.snowflake.com/en/developer-guide/snowflake-app-runtime/security) · [Hosted view results](verification.md#hosted-views)
