-- Render with manage.py bootstrap-sql and execute with CLI templating disabled.
${account_guard}
USE ROLE SECURITYADMIN;
CREATE ROLE IF NOT EXISTS ${dcm_role};
CREATE ROLE IF NOT EXISTS ${app_owner};
CREATE ROLE IF NOT EXISTS ${reader_role};
GRANT ROLE ${dcm_role} TO ROLE SYSADMIN;
GRANT ROLE ${app_owner} TO ROLE SYSADMIN;
GRANT ROLE ${reader_role} TO ROLE SYSADMIN;

USE ROLE SYSADMIN;
CREATE DATABASE IF NOT EXISTS ${database_name};
CREATE SCHEMA IF NOT EXISTS ${database_name}.DCM;
CREATE WAREHOUSE IF NOT EXISTS ${warehouse_name}
  WAREHOUSE_SIZE = XSMALL AUTO_SUSPEND = 60 AUTO_RESUME = TRUE INITIALLY_SUSPENDED = TRUE;
GRANT USAGE ON WAREHOUSE ${warehouse_name} TO ROLE ${dcm_role};
GRANT USAGE ON WAREHOUSE ${warehouse_name} TO ROLE ${app_owner};
GRANT USAGE ON WAREHOUSE ${warehouse_name} TO ROLE ${reader_role};
GRANT USAGE, CREATE SCHEMA ON DATABASE ${database_name} TO ROLE ${dcm_role};
GRANT USAGE ON DATABASE ${database_name} TO ROLE ${app_owner};
GRANT USAGE ON DATABASE ${database_name} TO ROLE ${reader_role};
GRANT USAGE, CREATE DCM PROJECT, CREATE STAGE ON SCHEMA ${database_name}.DCM TO ROLE ${dcm_role};

USE ROLE ${dcm_role};
CREATE DCM PROJECT IF NOT EXISTS ${database_name}.DCM.SNOWFASTAPI;
