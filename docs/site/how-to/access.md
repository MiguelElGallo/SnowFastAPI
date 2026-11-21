# Manage access to the API

Use this guide to give a group access to a service, check the privileges used to publish a dataset, or remove the group's access. Run grant changes as the administrator responsible for the object. The examples use the DEV names.

## Give a reader access

The demo bootstrap creates `SNOWFASTAPI_DEV_READER`. DCM grants it access to the demo table. The service owner grants it `USAGE` on the running service after publication. An administrator can grant that reader role to an existing role in the intended user's hierarchy.

For example, if `REPORTING_TEAM` is the reader's existing default role, the administrator who manages the role hierarchy can run the following grant. Substitute the intended role in your organization.

```sql
GRANT ROLE SNOWFASTAPI_DEV_READER TO ROLE REPORTING_TEAM;
```

For a customer dataset, check these two permissions separately.

| The user needs to | Grant to check |
| --- | --- |
| Open the service | A role available to the user has USAGE on the Application Service, its database and schema. |
| Read a published relation | The user's default role has USAGE on the source database and schema and the query warehouse, plus SELECT on the source relation. Existing row access and masking policies also apply. |

The service's execution role needs the matching restricted caller grants, which the publisher generates. Keep ordinary customer SELECT grants in your existing data-access process. [Snowflake app access control](https://docs.snowflake.com/en/developer-guide/snowflake-app-runtime/access-control) · [Caller grants](https://docs.snowflake.com/en/sql-reference/sql/grant-caller)

Check the service share and the execution role's caller privileges.

```sql
SHOW GRANTS ON APPLICATION SERVICE SNOWFASTAPI_DEV.API.SNOWFASTAPI;
SHOW CALLER GRANTS TO ROLE SNOWFASTAPI_DEV_OWNER;
```

Open two pages as the intended reader and compare the result with a direct query under that reader's default role. The [two-identity check](test.md#compare-two-identities) also covers masking.

## Verify the metadata identity

The metadata login reads column names, discovers primary keys and checks current key values during preparation. The publisher runs `USE SECONDARY ROLES NONE` before discovery. Choose a primary role with SELECT on every source and USAGE on the databases, schemas and metadata warehouse. To inspect the same context in a new SQL session, select that primary role, then run the following statements.

```sql
USE SECONDARY ROLES NONE;
SELECT CURRENT_ROLE(), CURRENT_SECONDARY_ROLES();
```

Pass the role with `--metadata-role`. An inaccessible relation fails preparation and identifies a grant to check before publishing. [Snowflake secondary roles](https://docs.snowflake.com/en/sql-reference/sql/use-secondary-roles)

## Replace a reader group

To move an audience from one team to another, keep the project reader role. Grant that role to the new team's role, have a member read a page, then revoke the membership from the old team. The service and its data grants stay available throughout this change.

```sql
GRANT ROLE SNOWFASTAPI_DEV_READER TO ROLE NEW_REPORTING_TEAM;
-- After the new team verifies a page:
REVOKE ROLE SNOWFASTAPI_DEV_READER FROM ROLE OLD_REPORTING_TEAM;
```

### Change the project reader role

Create a distinct, dedicated replacement role and set it as `reader_role` in the DCM target. For the metadata step, use a separate role that can already read the sources and use the query warehouse. If the replacement reader will also prepare metadata, first grant it USAGE on the project database and query warehouse. Apply the DCM definitions so it has the demo schema and table grants before running `prepare`. Review the generated grant and retirement SQL. DCM manages the demo table and schema grants. The publisher grants access to the project database, query warehouse and service. During a combined rotation, the publisher temporarily retains the outgoing reader’s existing DCM demo grants while it builds the new package. Once that package is healthy, it shares the service with the replacement role, revokes the previous project-managed share, and reapplies the final DCM definition. The grant administrator completes the retirement of the previous reader's project database and warehouse grants.

Use the split [release procedure](releases.md) to inspect changes before applying them. Check `SHOW GRANTS ON APPLICATION SERVICE` and make a request as a member of the replacement group. Other direct service shares, customer table grants and user role memberships are administered separately.
