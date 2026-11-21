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

The metadata login reads column names, discovers primary keys and checks current key values during `prepare`. Use a dedicated, narrowly privileged identity. In a session opened with the same connection and primary role, inspect its configured secondary roles.

```sql
SELECT CURRENT_ROLE(), CURRENT_SECONDARY_ROLES();
```

Selecting `--metadata-role` sets the primary role. This release retains the connection's default secondary roles, including any stronger role available there. A separate SQL session's `USE SECONDARY ROLES NONE` setting applies only to that session. Give the publishing identity appropriately scoped roles and check its defaults. [Snowflake secondary roles](https://docs.snowflake.com/en/sql-reference/sql/use-secondary-roles)

## Replace a reader group

First give the replacement role service and data access, then verify that a member can read the intended rows. Changing `reader_role` adds the new service share. The current deployer leaves the previous share in place.

Inspect `SHOW GRANTS ON APPLICATION SERVICE`. After verifying which grant belongs to the retiring group, revoke that specific share as the service owner. Replace `OLD_API_READER` with the reviewed role.

```sql
REVOKE USAGE ON APPLICATION SERVICE SNOWFASTAPI_DEV.API.SNOWFASTAPI
  FROM ROLE OLD_API_READER;
```

Check the grants again. A user can still open the service through another role grant. A user's existing direct access to source data is administered independently.
