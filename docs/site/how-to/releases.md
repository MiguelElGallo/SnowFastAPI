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

Omit `--previous` for the first publication. For later releases, pass the last successful catalog. New catalogs record the project reader. If an older catalog has no reader field, keep its original sibling `share.sql` with the release, or pass the verified role with `--previous-reader ROLE`. Review the changed projections, keys and limits in `catalog.diff` and the exact grant files.

## Apply grants and publish

The administrator applying `publisher-grants.sql` needs authority to grant schema CREATE privileges, account-level `BIND SERVICE ENDPOINT`, and ordinary USAGE on the project database and query warehouse. The second file needs a grant administrator with account-level `MANAGE CALLER GRANTS` and at least one privilege on each object named in a caller grant. In the example, `GRANT_ROLE` has both sets of privileges. If your organization assigns them separately, each administrator runs their file with their own connection and role. The service owner publishes the package and shares it with the configured reader. [Snowflake caller grant requirements](https://docs.snowflake.com/en/sql-reference/sql/grant-caller#access-control-requirements)

```sh
snow sql -c "$DEV_CONNECTION" --role "$GRANT_ROLE" --enable-templating NONE -f build/release-2/publisher-grants.sql
snow sql -c "$DEV_CONNECTION" --role "$GRANT_ROLE" --enable-templating NONE -f build/release-2/caller-grants.sql
uv run --frozen --group operator python manage.py publish -c "$DEV_CONNECTION" \
  --release build/release-2
snow sql -c "$DEV_CONNECTION" --role SNOWFASTAPI_DEV_OWNER --enable-templating NONE -f build/release-2/share.sql
```

Check the running package's `source` and `is_upgrading` in `DESCRIBE APPLICATION SERVICE SNOWFASTAPI_DEV.API.SNOWFASTAPI`. Read the changed route. When those checks pass, the caller-grant administrator applies a nonempty `retire-caller-grants.sql`. The administrator for ordinary database and warehouse grants applies a nonempty `retire-reader-grants.sql`. Run these files with CLI templating disabled. Keep the published catalog as the baseline for the next release.

Both `publish` and `deploy` identify the new immutable package version in the artifact repository. They wait for that version to be running at the service URL with its upgrade complete. The release directory records the repository, package and version in `published-artifact.json`. The combined command then shares the service, retires removed privileges and writes `last-published.json`. Use the split procedure to test a changed route before retirement. Persist release directories and serialize publications across all operators and CI runners for the same service. The file lock covers processes using the same operating-system user and lock directory. Coordinate separate hosts or accounts that can publish the same service.

## Keep access during a reader-role change

For a team membership change, follow [Replace a reader group](access.md#replace-a-reader-group). When a split release changes the actual `reader_role`, pass `--retain-reader OLD_READER` to the first `plan` and `apply-infra`. Replace `OLD_READER` with the verified old project reader. This preserves its existing DCM schema and demo table grants while the new service builds. Use the previous catalog for preparation. After verifying the package and sharing it with the new reader, run the final `plan` and `apply-infra` without that option. The final DCM pass retires the old demo grants. The combined deploy performs both passes for a recorded reader change.

## Remove a route

Delete its section from `tables.toml` while the old source object still exists. At least one dataset must remain in the file. Prepare against the last published catalog. Confirm the route disappears and that each proposed revocation belongs to the retired source. Grants needed by another configured route should remain. Publish, then verify that the removed HTTP path returns 404. In the split flow, run the nonempty `retire-caller-grants.sql` and verify `SHOW CALLER GRANTS TO ROLE` before the source owner drops or renames the relation.

If the source has already been dropped, Snowflake can return error 2003 when retiring its grant. With full grant visibility the retirement script checks the service owner’s caller-grant inventory. It accepts an absent grant when the inventory accounts for all matching grants. If it finds an unexplained grant, a possible rename, incomplete visibility or a different error, it stops. Inspect the current grant inventory and the live and previous catalogs before retrying. [Snowflake caller grants](https://docs.snowflake.com/en/sql-reference/sql/show-caller-grants)

## Recover a failed or unwanted release

1. Inspect the service's `status`, `source`, `is_upgrading` and URL. A failed build can leave a staging object and candidate caller grants. Compare `SHOW CALLER GRANTS TO ROLE` with the catalog that is serving traffic before removing a grant.
2. Restore the previous catalog’s exact caller grants. If the release changed the reader or warehouse, restore the previous reader’s database, warehouse and service USAGE. Plan and apply the matching DCM definition for its schema and demo SELECT grants. List versions with `SHOW VERSIONS IN ARTIFACT REPOSITORY SNOWFASTAPI_DEV.API.SNOWFASTAPI_REPO FOR PACKAGE SNOWFASTAPI`.
3. As service owner, select the previously verified version. For example, if your listing identifies `VERSION$4` as the intended version, run this statement in a SQL editor.

    ```sql
    ALTER APPLICATION SERVICE SNOWFASTAPI_DEV.API.SNOWFASTAPI
      UPGRADE TO VERSION VERSION$4;
    ```

4. Check the package version, open the route and follow a cursor. Verify access as the restored reader. Have the relevant administrators retire caller grants, service shares and ordinary grants that belonged only to the superseded release. Pass the catalog for the restored version with `--previous` when deploying again.

An App Runtime health-check failure can return the service to its last healthy version at the same URL. Version checks distinguish a successful rollout from a healthy older package. [Snowflake package deployment and rollback](https://docs.snowflake.com/en/developer-guide/snowflake-app-runtime/deploy)
