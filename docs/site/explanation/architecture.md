# How a request reaches Snowflake

A user opening the API and a Python process reading a table are two authorization decisions. Snowflake handles both. The application uses the caller's identity afresh for each data request.

<div class="sf-flow" role="group" aria-label="Request path from browser or client to gateway, service and warehouse">
<div class="sf-step"><strong>Snowflake gateway</strong><span>Authenticates the browser or Python client and checks access to the service.</span></div>
<div class="sf-step"><strong>FastAPI service</strong><span>Chooses the configured table, validates the page and opens a caller connection.</span></div>
<div class="sf-step"><strong>Query warehouse</strong><span>Runs a bound, read-only query with the caller's effective data access.</span></div>
</div>

## Which role reads the data

Service USAGE lets a user reach the application. For SQL, the serverless gateway supplies a complete caller OAuth token in `Sf-Context-Current-User-Token`. The service opens a new connector session with that token on the configured warehouse and closes it after the page. Users authenticate through Snowflake. The project needs no separate identity provider, user database or application signing secret.

App Runtime uses the signed-in user's default role for the data query. The role used to open the service can differ. An execution role's restricted caller grants set an additional boundary. For example, it needs caller SELECT on the published table, while the user needs ordinary SELECT. Snowflake applies the user's existing row and masking policies during the query. The deployed demo's execution role could not read the table with ordinary SELECT. [Runtime caller identity](https://docs.snowflake.com/en/developer-guide/snowflake-app-runtime/query-snowflake) · [App access control](https://docs.snowflake.com/en/developer-guide/snowflake-app-runtime/access-control)

## Why deployment has two parts

DCM, Snowflake's Database Change Management system, manages desired database definitions. Here it creates the API schema, demonstration table, seed view and supported grants. A separate seed command inserts missing fixture IDs. Customer datasets stay in their existing databases.

Snowflake CLI builds the Python package in an artifact repository and points the Application Service to a version. The publisher creates caller grants separately because DCM's supported grant types exclude caller grants. A release's frozen catalog connects the two sides. FastAPI can serve only the routes and columns captured there. [DCM supported entities](https://docs.snowflake.com/en/user-guide/dcm-projects/dcm-projects-supported-entities) · [App Runtime deployment](https://docs.snowflake.com/en/developer-guide/snowflake-app-runtime/deploy)

## What consumes credits

Serverless compute hosts the Python process. It can stop when idle and starts again on a request. The separate query warehouse executes SQL and can auto-suspend independently. The example warehouse is X-Small with a 60-second idle timeout. The service uses Snowflake's default 3,600-second idle timeout. Readiness uses the Python process alone. Preparing a release and reading data can resume a warehouse.

Python and serverless compute are public-preview features in the verified release. The paid DEV deployment served all five rows across repeated authenticated sessions. Account availability, the cost of warehouse scans and cold-start latency matter when choosing a deployment environment. [Serverless compute](https://docs.snowflake.com/en/developer-guide/snowflake-app-runtime/serverless) · [Idle timeout](https://docs.snowflake.com/en/developer-guide/snowflake-app-runtime/scale-and-suspend) · [Credit usage](https://docs.snowflake.com/en/developer-guide/snowflake-app-runtime/cost)
