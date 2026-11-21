# Release a change and recover a deployment

Use the split flow when different people administer infrastructure, approve access, and publish the application. Work in the implementation checkout. Use a new release directory for every candidate and keep the directory from the version currently serving requests.

## Prepare the candidate

Set `DEV_CONNECTION`, `METADATA_ROLE` and `GRANT_ROLE` as in [Deploy the demo](deploy.md). The DCM role owns the project. The metadata role must be able to read the configured sources.

```sh
uv run --frozen --group operator python manage.py plan -c "$DEV_CONNECTION"
```

Read the proposed DCM changes. Confirm the database, objects, grants and any removals before the DCM operator applies them. The examples use the same named connection throughout. With separate logins, each operator substitutes their own named connection to the same account for their step.

```sh
uv run --frozen --group operator python manage.py apply-infra -c "$DEV_CONNECTION"
uv run --frozen --group operator python manage.py prepare -c "$DEV_CONNECTION" \
  --metadata-role "$METADATA_ROLE" --output build/release-2 \
  --previous build/release-1/app/catalog.json
```

Omit `--previous` for the first publication. For later releases supply the catalog from the last successful release. Check `build/release-2/catalog.diff` for changed projections, keys, page limits and removed routes. Check the added and retired grants before proceeding.

## Apply grants and publish

The first file needs an administrator who can grant the schema CREATE privileges and the account-level `BIND SERVICE ENDPOINT` privilege. The second file needs a grant administrator with account-level `MANAGE CALLER GRANTS` and at least one privilege on each object named in a caller grant. In the example, `GRANT_ROLE` has both sets of privileges. If your organization assigns them separately, each administrator runs their file with their own connection and role. The service owner publishes the package and shares it with the configured reader. [Snowflake caller grant requirements](https://docs.snowflake.com/en/sql-reference/sql/grant-caller#access-control-requirements)

```sh
snow sql -c "$DEV_CONNECTION" --role "$GRANT_ROLE" -f build/release-2/publisher-grants.sql
snow sql -c "$DEV_CONNECTION" --role "$GRANT_ROLE" -f build/release-2/caller-grants.sql
uv run --frozen --group operator python manage.py publish -c "$DEV_CONNECTION" \
  --release build/release-2
snow sql -c "$DEV_CONNECTION" --role SNOWFASTAPI_DEV_OWNER -f build/release-2/share.sql
```

Check the running package's `source` and `is_upgrading` in `DESCRIBE APPLICATION SERVICE SNOWFASTAPI_DEV.API.SNOWFASTAPI`. Read the changed route. When those checks pass, the grant administrator applies `retire-caller-grants.sql` if the file is nonempty. Keep the published catalog as the baseline for the next release.

The combined `deploy` command checks for a running service URL and completed upgrade, then shares the service, retires privileges and writes `last-published.json`. Checking the specific package version and reading a changed route are operator checks. Use the split procedure above when they must happen before grant retirement. Persist `build/deployments/` across CI runs and serialize deploys for the same service. The built-in file lock coordinates processes sharing one local checkout.

## Remove a route

Delete its section from `tables.toml` while the old source object still exists. At least one dataset must remain in the file. Prepare against the last published catalog. Confirm the route disappears and that each proposed revocation belongs to the retired source. Grants needed by another configured route should remain. Publish, then verify that the removed HTTP path returns 404. In the split flow, run the nonempty `retire-caller-grants.sql` and verify `SHOW CALLER GRANTS TO ROLE` before the source owner drops or renames the relation.

If the source was already renamed or dropped, an old-name revoke can fail with Snowflake error 2003 after the new package goes live. Check the service's actual version, the current caller grants, and both release catalogs. An administrator must reconcile the removed or renamed object and verify each outstanding privilege before adopting the live catalog as the next baseline. Retrying the same old-name revoke can repeat the error.

## Recover a failed or unwanted release

1. Inspect the service's `status`, `source`, `is_upgrading` and URL. A failed build can leave a staging object and candidate caller grants. Compare `SHOW CALLER GRANTS TO ROLE` with the catalog that is serving traffic before removing a grant.
2. If you need a previous working version, restore its exact caller grants. List versions with `SHOW VERSIONS IN ARTIFACT REPOSITORY SNOWFASTAPI_DEV.API.SNOWFASTAPI_REPO FOR PACKAGE SNOWFASTAPI`.
3. As service owner, select the previously verified version. For example, if your listing identifies `VERSION$4` as the intended version, run this statement in a SQL editor.

    ```sql
    ALTER APPLICATION SERVICE SNOWFASTAPI_DEV.API.SNOWFASTAPI
      UPGRADE TO VERSION VERSION$4;
    ```

4. Check the package version, open the route and follow a cursor. Have the grant administrator retire privileges used only by the superseded release. Pass the catalog for the restored version with `--previous` when deploying again.

An App Runtime health-check failure can return the service to its last healthy version at the same URL. Version checks distinguish a successful rollout from a healthy older package. [Snowflake package deployment and rollback](https://docs.snowflake.com/en/developer-guide/snowflake-app-runtime/deploy)
