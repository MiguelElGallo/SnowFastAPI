"""Compile table configuration into the immutable catalog shipped with a release."""

import difflib
import re
import shutil
import tempfile
import tomllib
from contextlib import closing
from pathlib import Path
from string import Template
from typing import Annotated, Literal

import yaml
from pydantic import Field, model_validator

from app.snowapi.catalog import Alias, Catalog, Column, Dataset, Model, Name, PageSize, quoted
from app.snowapi.paging import MAX_TEXT_KEY_BYTES

ROOT = Path(__file__).resolve().parent
IDENTIFIER = r'(?:[A-Za-z_][A-Za-z0-9_$]*|"(?:[^"]|"")+")'
SIMPLE_NAME = r"[A-Z_][A-Z0-9_]*"
ACCOUNT_QUERY = "SELECT CURRENT_ORGANIZATION_NAME() || '-' || CURRENT_ACCOUNT_NAME() AS ACCOUNT"
SYSTEM_ROLES = {
    "PUBLIC",
    "ACCOUNTADMIN",
    "SECURITYADMIN",
    "SYSADMIN",
    "USERADMIN",
    "ORGADMIN",
    "GLOBALORGADMIN",
}


def account_identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_-]*-[A-Za-z0-9_][A-Za-z0-9_-]*", value):
        raise ValueError("Use an organization-account identifier such as MYORG-MYACCOUNT")
    return value.upper()


def account_guard(account: str) -> str:
    return (
        "EXECUTE IMMEDIATE $$\n"
        "DECLARE\n  wrong_account EXCEPTION (-20001, 'Wrong Snowflake deployment account');\n"
        "BEGIN\n"
        f"  IF (CURRENT_ORGANIZATION_NAME() || '-' || CURRENT_ACCOUNT_NAME() <> '{account_identifier(account)}') THEN\n"
        "    RAISE wrong_account;\n  END IF;\nEND;\n$$;\nUSE SECONDARY ROLES NONE;\n"
    )


def managed_role(name: str) -> str:
    if not re.fullmatch(SIMPLE_NAME, name) or name in SYSTEM_ROLES:
        raise ValueError(f"Use a dedicated, simple uppercase project role: {name!r}")
    return name


def identifiers(raw: str) -> tuple[str, ...]:
    if not re.fullmatch(rf"{IDENTIFIER}(?:\.{IDENTIFIER})*", raw):
        raise ValueError(f"Invalid Snowflake identifier: {raw!r}")
    parts = tuple(
        x[1:-1].replace('""', '"') if x.startswith('"') else x.upper()
        for x in re.findall(IDENTIFIER, raw)
    )
    if any(len(x) > 255 or any(ord(c) < 32 for c in x) for x in parts):
        raise ValueError("Snowflake identifiers must be printable and at most 255 characters")
    return parts


def column_name(raw: str) -> str:
    parts = identifiers(raw)
    if len(parts) != 1:
        raise ValueError(f"Expected one column name: {raw!r}")
    return parts[0]


class TableSpec(Model):
    table: str
    kind: Literal["table", "view"] = "table"
    columns: Annotated[tuple[str, ...], Field(min_length=1)] | None = None
    key: Annotated[tuple[str, ...], Field(min_length=1, max_length=4)] | None = None
    max_page_size: PageSize = 100


class Config(Model):
    tables: Annotated[dict[Alias, TableSpec], Field(min_length=1)]


class Deployment(Model):
    database_name: Name
    warehouse_name: Name
    app_owner: Name
    reader_role: Name
    dcm_role: Name
    account_identifier: str | None = None

    @model_validator(mode="after")
    def validate_target(self):
        for name in (self.database_name, self.warehouse_name):
            if not re.fullmatch(SIMPLE_NAME, name):
                raise ValueError("Deployment object names must be simple uppercase identifiers")
        roles = [managed_role(name) for name in (self.app_owner, self.reader_role, self.dcm_role)]
        if len(set(roles)) != len(roles):
            raise ValueError("The app owner, reader and DCM owner must be distinct project roles")
        if self.account_identifier:
            account_identifier(self.account_identifier)
        return self

    @classmethod
    def load(cls):
        manifest = yaml.safe_load((ROOT / "dcm/manifest.yml").read_text())
        target = manifest["targets"][manifest["default_target"]]
        values = manifest["templating"]["configurations"][target["templating_config"]]
        deployment = cls(
            **values,
            dcm_role=target["project_owner"],
            account_identifier=target.get("account_identifier"),
        )
        if target["project_name"] != f"{deployment.database_name}.DCM.SNOWFASTAPI":
            raise ValueError("DCM project_name must match the configured database")
        return deployment

    @property
    def service(self):
        return f"{self.database_name}.API.SNOWFASTAPI"

    def bootstrap(self, account: str):
        if self.account_identifier and account_identifier(
            self.account_identifier
        ) != account_identifier(account):
            raise ValueError("Bootstrap account does not match the DCM target")
        return Template((ROOT / "setup/bootstrap.sql").read_text()).substitute(
            **self.model_dump(), account_guard=account_guard(account)
        )


def metadata(db) -> list[dict]:
    fields = [field.name.lower() for field in db.description]
    return [dict(zip(fields, row, strict=True)) for row in db.fetchall()]


def compile_table(db, spec: TableSpec, database: str) -> Dataset:
    source = identifiers(spec.table)
    if len(source) == 1:
        source = (database, "API", source[0])
    if len(source) != 3:
        raise ValueError("Use a fully qualified DB.SCHEMA.TABLE or a name in the API schema")
    relation = ".".join(map(quoted, source))
    db.execute(f"DESCRIBE {spec.kind.upper()} {relation}")
    columns = {
        row["name"]: Column(name=row["name"], sql_type=row["type"].upper())
        for row in metadata(db)
        if row["kind"] == "COLUMN"
    }
    selected = [column_name(c) for c in spec.columns] if spec.columns else list(columns)
    if missing := set(selected).difference(columns):
        raise ValueError(f"{relation}: unknown projected columns {sorted(missing)}")
    if spec.key:
        key = [column_name(c) for c in spec.key]
    elif spec.kind == "table":
        db.execute(f"SHOW PRIMARY KEYS IN TABLE {relation}")
        key = [r["column_name"] for r in sorted(metadata(db), key=lambda r: int(r["key_sequence"]))]
    else:
        key = []
    if not key:
        raise ValueError(
            f"{relation}: set key to an immutable unique column or tuple in tables.toml"
        )
    dataset = Dataset(
        source=source,
        kind=spec.kind,
        columns=[columns[c] for c in selected],
        key=key,
        max_page_size=spec.max_page_size,
    )
    keys = [c.ordered_sql for c in dataset.key_columns]
    invalid = [f"{k} IS NULL" for k in keys] + ["COUNT(*) > 1"]
    for column in dataset.key_columns:
        if column.key_type == "text":
            invalid.append(f"OCTET_LENGTH({column.ordered_sql}) > {MAX_TEXT_KEY_BYTES}")
    db.execute(
        f"SELECT 1 FROM {relation} GROUP BY {', '.join(keys)} HAVING {' OR '.join(invalid)} LIMIT 1"
    )
    if db.fetchone():
        raise ValueError(f"{relation}: duplicate, null or overlong pagination key")
    return dataset


def current_account(connection) -> str:
    with closing(connection.cursor()) as db:
        db.execute(ACCOUNT_QUERY)
        row = db.fetchone()
        if not row or not isinstance(row[0], str):
            raise ValueError("Snowflake did not return an organization and account")
        return account_identifier(row[0])


def compile_catalog(connection, config: Path, deployment: Deployment) -> Catalog:
    specs = Config.model_validate(tomllib.loads(config.read_text()))
    account = current_account(connection)
    with closing(connection.cursor()) as db:
        db.execute("USE SECONDARY ROLES NONE")
        tables = {
            name: compile_table(db, spec, deployment.database_name)
            for name, spec in specs.tables.items()
        }
    return Catalog(
        account=account,
        service=deployment.service,
        owner=deployment.app_owner,
        warehouse=deployment.warehouse_name,
        reader_role=deployment.reader_role,
        tables=tables,
    )


def caller_privileges(catalog: Catalog) -> set[tuple[str, str, str]]:
    privileges = {("USAGE", "WAREHOUSE", quoted(catalog.warehouse))}
    for table in catalog.tables.values():
        db, schema, _ = map(quoted, table.source)
        privileges.update(
            {
                ("USAGE", "DATABASE", db),
                ("USAGE", "SCHEMA", f"{db}.{schema}"),
                ("SELECT", table.kind.upper(), table.qualified),
            }
        )
    return privileges


def sql_literal(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def grant_spellings(name: str) -> set[str]:
    parts = identifiers(name)
    display = ".".join(p if re.fullmatch(r"[A-Z_][A-Z0-9_$]*", p) else quoted(p) for p in parts)
    spellings = {name, display}
    # Dropping identifier quotes can collapse two distinct multipart names into one.
    if all("." not in p and '"' not in p for p in parts):
        spellings.add(".".join(parts))
    return spellings


def retire_caller_sql(
    owner: str, grant: tuple[str, str, str], known: set[tuple[str, str, str]]
) -> str:
    # Missing objects and insufficient access can both return 2003. Only an administrator
    # with complete visibility can prove that a missing grant has already been retired.
    privilege, kind, name = grant
    names = set().union(*(grant_spellings(n) for p, k, n in known if (p, k) == (privilege, kind)))
    known_names = ", ".join(map(sql_literal, sorted(names)))
    spellings = ", ".join(map(sql_literal, sorted(grant_spellings(name))))
    revoke = f"REVOKE CALLER {privilege} ON {kind} {name} FROM ROLE {quoted(owner)}"
    block = f"""DECLARE
  manage_grants NUMBER;
  rows_seen NUMBER;
  unresolved NUMBER;
BEGIN
  EXECUTE IMMEDIATE {sql_literal(revoke)};
EXCEPTION WHEN STATEMENT_ERROR THEN
  IF (SQLCODE <> 2003) THEN
    RAISE;
  END IF;
  SHOW GRANTS ON ACCOUNT;
  SELECT COUNT(*) INTO :manage_grants FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()))
    WHERE "privilege" = 'MANAGE GRANTS' AND IS_ROLE_IN_SESSION("grantee_name");
  IF (manage_grants = 0) THEN
    RAISE;
  END IF;
  SHOW CALLER GRANTS TO ROLE {quoted(owner)};
  SELECT COUNT(*), COUNT_IF("privilege" = {sql_literal(privilege)}
    AND "granted_on" = {sql_literal(kind)} AND NOT "is_inherited"::BOOLEAN
    AND ("name" IN ({spellings}) OR "name" NOT IN ({known_names}))) INTO :rows_seen, :unresolved
    FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()));
  IF (rows_seen >= 10000 OR COALESCE(unresolved, 0) > 0) THEN
    RAISE;
  END IF;
END;"""
    return "EXECUTE IMMEDIATE " + sql_literal(block) + ";\n"


def grants_sql(catalog: Catalog, previous: Catalog | None = None, *, retire=False) -> str:
    desired = caller_privileges(catalog)
    if retire:
        old = caller_privileges(previous) if previous else set()
        return "".join(
            retire_caller_sql(catalog.owner, grant, old | desired)
            for grant in sorted(old - desired)
        )
    return "".join(
        f"GRANT CALLER {priv} ON {kind} {name} TO ROLE {quoted(catalog.owner)};\n"
        for priv, kind, name in sorted(desired)
    )


def retire_reader_sql(reader: str, kind: str, name: str) -> str:
    revoke = f"REVOKE USAGE ON {kind} {name} FROM ROLE {quoted(reader)}"
    if kind == "APPLICATION SERVICE":
        # The service owner has complete visibility of direct privileges on this service.
        proof = f"""DESCRIBE APPLICATION SERVICE {name};
  SELECT COUNT(*) INTO :visible FROM TABLE(RESULT_SCAN(LAST_QUERY_ID())) WHERE "owner" = CURRENT_ROLE();
  IF (visible <> 1) THEN RAISE; END IF;
  SHOW GRANTS ON APPLICATION SERVICE {name};
  SELECT COUNT(*), COUNT_IF("grantee_name" = {sql_literal(reader)} AND "granted_to" = 'ROLE'
    AND "privilege" = 'USAGE') INTO :rows_seen, :visible FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()));"""
    else:
        # A grant administrator may see a filtered object list. Only a role with full
        # account-wide visibility may infer that a role, warehouse, or database is gone.
        object_name = identifiers(name)[0]
        objects = {"DATABASE": "DATABASES", "WAREHOUSE": "WAREHOUSES"}[kind]
        proof = f"""SHOW GRANTS ON ACCOUNT;
  SELECT COUNT(*) INTO :visible FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()))
    WHERE "privilege" = 'MANAGE GRANTS' AND IS_ROLE_IN_SESSION("grantee_name");
  IF (visible = 0) THEN RAISE; END IF;
  SHOW ROLES LIKE {sql_literal(reader)};
  SELECT COUNT(*), COUNT_IF("name" = {sql_literal(reader)})
    INTO :rows_seen, :visible FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()));
  IF (rows_seen < 10000 AND COALESCE(visible, 0) = 0) THEN
    RETURN 'Outgoing role is absent';
  END IF;
  SHOW {objects} LIKE {sql_literal(object_name)};
  SELECT COUNT(*), COUNT_IF("name" = {sql_literal(object_name)})
    INTO :rows_seen, :visible FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()));"""
    block = f"""DECLARE
  rows_seen NUMBER;
  visible NUMBER;
BEGIN
  EXECUTE IMMEDIATE {sql_literal(revoke)};
EXCEPTION WHEN STATEMENT_ERROR THEN
  IF (SQLCODE NOT IN (2003, 2043) OR SQLSTATE NOT IN ('42S02', '02000')) THEN RAISE; END IF;
  {proof}
  IF (rows_seen >= 10000 OR COALESCE(visible, 0) > 0) THEN RAISE; END IF;
END;"""
    return "EXECUTE IMMEDIATE " + sql_literal(block) + ";\n"


def read_previous(path: Path | None, previous_reader: str | None = None) -> Catalog | None:
    if path is None:
        if previous_reader:
            raise ValueError("--previous-reader requires a previous catalog")
        return None
    data = path.read_bytes()
    catalog = Catalog.model_validate_json(data)
    if catalog.reader_role:
        if previous_reader and previous_reader != catalog.reader_role:
            raise ValueError("--previous-reader conflicts with the catalog's recorded reader")
        return catalog
    # Pre-reader receipts copied catalog.json verbatim. Only accept share SQL written
    # for a matching release and service. Never infer ownership from current cloud shares.
    if path.parent.name == "app":
        candidates = [path]
    elif path.name == "last-published.json":
        candidates = sorted(path.parent.glob("*/app/catalog.json"))
    else:
        candidates = []
    readers = set()
    for candidate in candidates:
        share = candidate.parent.parent / "share.sql"
        if candidate.read_bytes() == data and share.is_file():
            match = re.fullmatch(
                rf'GRANT USAGE ON APPLICATION SERVICE {re.escape(catalog.service)} TO ROLE "({SIMPLE_NAME})";',
                share.read_text().strip(),
            )
            if match:
                readers.add(match[1])
    if previous_reader:
        reader = managed_role(previous_reader)
        if readers and reader not in readers:
            raise ValueError("--previous-reader conflicts with the previous release's share.sql")
    elif len(readers) == 1:
        (reader,) = readers
    else:
        raise ValueError("Legacy catalog: identify its managed role with --previous-reader ROLE")
    return catalog.model_copy(update={"reader_role": reader})


def build_release(catalog: Catalog, deployment: Deployment, output: Path, previous: Catalog | None):
    if previous and (previous.account, previous.service, previous.owner) != (
        catalog.account,
        catalog.service,
        catalog.owner,
    ):
        raise ValueError("The previous catalog must belong to this service and execution role")
    catalog = catalog.model_copy(update={"reader_role": deployment.reader_role})
    previous_reader = (
        managed_role(previous.reader_role) if previous and previous.reader_role else None
    )
    if previous_reader in (deployment.app_owner, deployment.dcm_role):
        raise ValueError("The outgoing reader must be distinct from both project owners")
    output = output.resolve()
    if output.exists():
        raise ValueError(f"{output} already exists. Choose a new directory for this release")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as tmp:
        release = Path(tmp) / "release"
        app = release / "app"
        app.mkdir(parents=True)
        for file in ("serve.py", "requirements.txt"):
            shutil.copyfile(ROOT / "app" / file, app / file)
        code = app / "snowapi"
        code.mkdir()
        for name in ("__init__.py", "catalog.py", "paging.py", "api.py"):
            shutil.copyfile(ROOT / "app/snowapi" / name, code / name)
        manifest = yaml.safe_load((ROOT / "app/app.yml").read_text())
        manifest.update(
            database=deployment.database_name,
            query_warehouse=catalog.warehouse,
            build_job_location=f"{deployment.database_name}.API",
        )
        (app / "app.yml").write_text(yaml.safe_dump(manifest, sort_keys=False))
        current = catalog.model_dump_json(indent=2) + "\n"
        (app / "catalog.json").write_text(current)
        old = previous.model_dump_json(indent=2) + "\n" if previous else ""
        diff = difflib.unified_diff(
            old.splitlines(True),
            current.splitlines(True),
            fromfile="previous/catalog.json",
            tofile="candidate/catalog.json",
        )
        (release / "catalog.diff").write_text("".join(diff))
        guard = account_guard(catalog.account)
        (release / "caller-grants.sql").write_text(guard + grants_sql(catalog))
        retire = grants_sql(catalog, previous, retire=True)
        retire_reader = ""
        schema = ".".join([quoted(deployment.database_name), '"API"'])
        # The CLI uploads to a stage and builds into a per-service artifact repository.
        (release / "publisher-grants.sql").write_text(
            guard
            + f"GRANT CREATE STAGE, CREATE SERVICE, CREATE ARTIFACT REPOSITORY, CREATE APPLICATION SERVICE "
            f"ON SCHEMA {schema} TO ROLE {quoted(catalog.owner)};\n"
            f"GRANT BIND SERVICE ENDPOINT ON ACCOUNT TO ROLE {quoted(catalog.owner)};\n"
            f"GRANT USAGE ON DATABASE {quoted(deployment.database_name)} TO ROLE {quoted(deployment.reader_role)};\n"
            f"GRANT USAGE ON WAREHOUSE {quoted(catalog.warehouse)} TO ROLE {quoted(deployment.reader_role)};\n"
        )
        share = (
            f"GRANT USAGE ON APPLICATION SERVICE {deployment.service} "
            f"TO ROLE {quoted(deployment.reader_role)};\n"
        )
        if previous and previous_reader and previous_reader != deployment.reader_role:
            share += retire_reader_sql(previous_reader, "APPLICATION SERVICE", deployment.service)
            retire_reader += retire_reader_sql(
                previous_reader, "DATABASE", quoted(deployment.database_name)
            )
            retire_reader += retire_reader_sql(
                previous_reader, "WAREHOUSE", quoted(previous.warehouse)
            )
        elif previous and previous.warehouse != catalog.warehouse:
            retire_reader += retire_reader_sql(
                deployment.reader_role, "WAREHOUSE", quoted(previous.warehouse)
            )
        (release / "share.sql").write_text(guard + share)
        (release / "retire-caller-grants.sql").write_text(guard + retire if retire else "")
        (release / "retire-reader-grants.sql").write_text(
            guard + retire_reader if retire_reader else ""
        )
        release.rename(output)
    return output
