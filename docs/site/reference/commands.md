# Commands and release files

Run application commands in the implementation checkout. Use Python 3.13 and the checked-in uv lockfile. The documentation repository can be built independently as described in its README.

## Python client

```text
python client.py TABLE -c CONNECTION [--service DB.SCHEMA.APP] [--role ROLE] [--limit N] [--pages N]
python client.py URL TABLE [--channel chromium|chrome|msedge] [--headless] [--limit N] [--pages N]
```

| Argument or option | Behavior |
| --- | --- |
| `TABLE` | Required route name such as `demo`. The SQL object name can differ. |
| `-c`, `--connection` | Named Snowflake connection. Discovers the HTTPS origin using DESCRIBE APPLICATION SERVICE. Choose this mode or supply a URL. |
| `--service` | Connection mode service identifier, default `SNOWFASTAPI_DEV.API.SNOWFASTAPI`. |
| `--role` | Session role for service discovery in connection mode. If omitted, the connection's configured role applies. |
| `URL` | Browser mode service origin. The hosted origin must use HTTPS under `.snowflake.app`. Loopback origins are accepted for local tests. |
| `--limit` | Positive integer with default 2. The service enforces its configured ceiling. |
| `--pages` | Maximum number of pages to print, default 2. A null cursor stops earlier. |
| `--channel` | Browser selection, default `chromium`. The client dependency group supplies Playwright. |
| `--headless` | Runs the browser without a window. Useful for an accessible local test origin. Interactive Snowflake sign-in normally needs a visible window. |

## Deployment commands

Use `uv run --frozen --group operator python manage.py COMMAND`. All commands except `bootstrap-sql` require `-c CONNECTION` or `--connection CONNECTION`.

| Command | Additional options | Effects |
| --- | --- | --- |
| `bootstrap-sql` | None | Prints the administrator SQL for the selected DEV manifest. Executing the output creates the bootstrap objects. |
| `plan` | None | Uploads and plans the DCM definitions. Reports proposed changes without applying them. |
| `apply-infra` | None | Runs a DCM plan and deploy, then inserts any missing demo IDs. |
| `prepare` | Required `--output NEW_DIR`. Optional `--config`, `--previous`, `--metadata-role`, `--metadata-warehouse`. | Reads Snowflake metadata and validates keys. Writes a new release directory. |
| `publish` | Required `--release DIR`. | Validates the prepared service, owner, account and warehouse, deploys via Snowflake CLI and waits for a running service URL. |
| `deploy` | Required `--grant-role ROLE`. Optional `--config`, `--previous`, `--metadata-role`, `--metadata-warehouse`. | Performs infrastructure, preparation, grants, publication, sharing and retirement in order. |

`--config` defaults to the checkout's `tables.toml`. The metadata warehouse defaults to the deployment warehouse. `--previous` takes a catalog JSON file. In combined deploy mode, the command uses the last local success receipt when no explicit baseline is supplied. A separate `prepare` needs its baseline passed explicitly.

## Release directory

| Path | Contents or intended operator |
| --- | --- |
| `app/` | Package uploaded to Snowflake, including `app.yml`, the runtime and locked dependencies. |
| `app/catalog.json` | Frozen route names, projections, pagination keys, service, owner, warehouse and account. |
| `catalog.diff` | Proposed catalog compared with the supplied baseline. |
| `publisher-grants.sql` | Deployment privileges for the dedicated service owner. Administrator reviews and applies. |
| `caller-grants.sql` | Exact privileges the owner may exercise on the caller's behalf. |
| `share.sql` | Service USAGE grant for the configured reader. |
| `retire-caller-grants.sql` | Previously published caller privileges removed by the candidate. Apply after verification. |

Combined deployments store immutable preparation directories and `last-published.json` under `build/deployments/<account>/<service>/`. A readiness check polls for up to five minutes after the CLI deployment step. It checks status, URL and upgrade state. To verify the specific package version, inspect the service's `source` field. [Release procedure](../how-to/releases.md)
