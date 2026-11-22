import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import yaml
from filelock import Timeout

import manage
from app.snowapi.catalog import Catalog, Column, Dataset
from client import service_origin
from publishing import (
    Deployment,
    TableSpec,
    build_release,
    compile_catalog,
    compile_table,
    grant_spellings,
    grants_sql,
    identifiers,
    read_previous,
)


class MetaCursor:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.queries = []

    def execute(self, sql):
        self.queries.append(sql)
        header, self.rows = next(self.responses)
        self.description = [SimpleNamespace(name=name) for name in header]

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return next(iter(self.rows), None)

    def close(self):
        pass


def columns():
    return (
        ["kind", "name", "type"],
        [
            ("COLUMN", "CODE", "VARCHAR(20)"),
            ("COLUMN", "ID", "NUMBER(38,0)"),
            ("COLUMN", "EXTRA", "VARCHAR(20)"),
        ],
    )


def test_table_only_configuration():
    db = MetaCursor(
        [columns(), (["column_name", "key_sequence"], [("ID", 2), ("CODE", 1)]), ([], [])]
    )
    result = compile_table(db, TableSpec(table="DB.PUBLIC.Orders", max_page_size=5), "DB")
    assert result.key == ("CODE", "ID") and result.max_page_size == 5
    assert [c.name for c in result.columns] == ["CODE", "ID", "EXTRA"]
    assert db.queries[1] == 'SHOW PRIMARY KEYS IN TABLE "DB"."PUBLIC"."ORDERS"'
    assert "COUNT(*) > 1" in db.queries[2]


def test_explicit_view_key_is_checked_against_data():
    spec = TableSpec(table="MY_VIEW", kind="view", key=("ID",), columns=("ID", "CODE"))
    with pytest.raises(ValueError, match="duplicate, null"):
        compile_table(MetaCursor([columns(), ([], [(1,)])]), spec, "DB")
    good = compile_table(MetaCursor([columns(), ([], [])]), spec, "DB")
    assert [col.name for col in good.columns] == ["ID", "CODE"]


def test_keyless_source_requires_configuration():
    with pytest.raises(ValueError, match="set key"):
        compile_table(MetaCursor([columns(), ([], [])]), TableSpec(table="T"), "DB")


def test_unsupported_key_type():
    with pytest.raises(ValueError, match="unsupported pagination type"):
        Dataset(
            source=("DB", "S", "T"),
            kind="table",
            columns=(Column(name="TS", sql_type="TIMESTAMP_NTZ(9)"),),
            key=("TS",),
        )


def test_identifier_round_trip():
    assert identifiers('db."A.B"."a""b"') == ("DB", "A.B", 'a"b')
    with pytest.raises(ValueError):
        identifiers("db..t")


def test_recovery_rejects_ambiguous_unquoted_object_names():
    assert "DB.A.B.T" not in grant_spellings('"DB"."A.B"."T"')
    assert "DB.A.B.T" not in grant_spellings('"DB"."A"."B.T"')
    assert 'DB.A.B"T' not in grant_spellings('"DB"."A"."B""T"')


def test_release_scope_revocations_and_contents(tmp_path):
    deployment = Deployment.load()
    old = Dataset(
        source=("EXTERNAL", "S", "PREVIOUS"),
        kind="table",
        columns=(Column(name="ID", sql_type="NUMBER(38,0)"),),
        key=("ID",),
    )
    new = old.model_copy(update={"source": ("EXTERNAL", "S", "CURRENT"), "kind": "view"})
    before = Catalog(
        account="TEST-ACCOUNT",
        service=deployment.service,
        owner=deployment.app_owner,
        warehouse=deployment.warehouse_name,
        tables={"demo": old},
    )
    after = before.model_copy(update={"tables": {"demo": new}})
    directory = build_release(after, deployment, tmp_path / "v2", before)
    revoke = (directory / "retire-caller-grants.sql").read_text()
    assert revoke.count("REVOKE") == 1 and 'SELECT ON TABLE "EXTERNAL"."S"."PREVIOUS"' in revoke
    assert 'GRANT CALLER SELECT ON VIEW "EXTERNAL"."S"."CURRENT"' in grants_sql(after)
    assert sorted(f.name for f in (directory / "app").iterdir()) == [
        "app.yml",
        "catalog.json",
        "requirements.txt",
        "serve.py",
        "snowapi",
    ]
    manifest = yaml.safe_load((directory / "app/app.yml").read_text())
    assert (manifest["runtime"], manifest["compute_resource"]) == ("python", "SERVERLESS")
    assert "PREVIOUS" in (directory / "catalog.diff").read_text()
    with pytest.raises(ValueError, match="already exists"):
        build_release(after, deployment, directory, before)


@pytest.mark.parametrize(
    "url",
    [
        "http://app.example.com",
        "https://test.snowflake.app/path",
        "https://user@demo.snowflake.app",
    ],
)
def test_client_origin_validation(url):
    with pytest.raises(ValueError):
        service_origin(url)


def test_publish_readiness_observes_running_url(monkeypatch):
    expected = manage.Artifact("DB.API.PACKAGES", "APP", "VERSION$4")
    source = {
        "artifactRepository": expected.repository,
        "package": expected.package,
        "version": expected.version,
    }
    fields = ["status", "url", "is_upgrading", "source"]
    db = MetaCursor(
        [
            (["status", "url"], [("PENDING", None)]),
            (["status", "url"], [("RUNNING", "provisioning in progress")]),
            (fields, [("RUNNING", "demo.snowflake.app", True, source)]),
            (
                fields,
                [("RUNNING", "demo.snowflake.app", False, {**source, "version": "VERSION$3"})],
            ),
            (fields, [("RUNNING", "demo.snowflake.app", False, {**source, "package": "OTHER"})]),
            (fields, [("RUNNING", "demo.snowflake.app", False, json.dumps(source))]),
        ]
    )
    conn = MagicMock()
    conn.cursor.return_value = db
    monkeypatch.setattr("manage.time.sleep", lambda _: None)
    manage.wait_for_service(conn, "DB.API.APP", expected)
    assert len(db.queries) == 6


@pytest.fixture
def catalog():
    dep = Deployment.load()
    dataset = Dataset(
        source=("DB", "APP", "R&D"),
        kind="table",
        columns=(Column(name="ID", sql_type="NUMBER(38,0)"),),
        key=("ID",),
    )
    return Catalog(
        account="TEST-ACCOUNT",
        service=dep.service,
        owner=dep.app_owner,
        warehouse=dep.warehouse_name,
        reader_role=dep.reader_role,
        tables={"items": dataset},
    )


@pytest.mark.parametrize(
    "roles",
    [
        {"reader_role": "PUBLIC"},
        {"app_owner": "SECURITYADMIN"},
        {"dcm_role": "SYSADMIN"},
        {"reader_role": "SAME", "dcm_role": "SAME"},
        {"reader_role": "A", "app_owner": "A"},
        {"dcm_role": "bad role"},
    ],
)
def test_project_roles_are_dedicated(roles):
    with pytest.raises(ValueError, match="role"):
        Deployment(**(Deployment.load().model_dump() | roles))


def test_bootstrap_guard_precedes_ddl_and_validates_pinned_target():
    dep = Deployment(**(Deployment.load().model_dump() | {"account_identifier": "test-account"}))
    script = dep.bootstrap("TEST-ACCOUNT")
    assert script.index("CURRENT_ACCOUNT_NAME() <> 'TEST-ACCOUNT'") < script.index(
        "USE ROLE SECURITYADMIN"
    )
    with pytest.raises(ValueError, match="DCM target"):
        dep.bootstrap("TEST-DIFFERENT")
    with pytest.raises(ValueError, match="organization-account"):
        dep.bootstrap("wrong account")


@pytest.mark.parametrize(
    "command,args",
    [
        ("plan", []),
        ("apply-infra", []),
        ("prepare", ["--output", "unused"]),
        ("deploy", ["--grant-role", "SECURITYADMIN"]),
        ("publish", ["--release"]),
        ("bootstrap-sql", []),
    ],
)
def test_every_entrypoint_detects_disagreeing_clients_before_mutation(
    command, args, tmp_path, catalog, monkeypatch
):
    release = build_release(catalog, Deployment.load(), tmp_path / "release", None)
    args = [*args, str(release)] if command == "publish" else args
    monkeypatch.setattr(sys, "argv", ["manage.py", command, "-c", "profile", *args])
    conn = MagicMock()
    conn.cursor.return_value.fetchone.return_value = (catalog.account,)
    monkeypatch.setattr("snowflake.connector.connect", lambda **kwargs: conn)
    run = MagicMock(return_value=SimpleNamespace(stdout='[{"ACCOUNT":"OTHER-ACCOUNT"}]'))
    monkeypatch.setattr("manage.subprocess.run", run)
    with pytest.raises(ValueError, match="different accounts"):
        manage.main()
    run.assert_called_once()
    assert run.call_args.args[0][:2] == ["snow", "sql"]
    assert "CURRENT_ACCOUNT_NAME()" in run.call_args.args[0][run.call_args.args[0].index("-q") + 1]


def test_metadata_uses_primary_role_and_warehouse(tmp_path, catalog, monkeypatch):
    config = tmp_path / "tables.toml"
    config.write_text('[tables.items]\ntable = "T"\n')
    db = MagicMock()
    conn = MagicMock()
    conn.cursor.return_value = db
    db.fetchone.return_value = (catalog.account,)

    def compile_one(cursor, spec, database):
        assert cursor.execute.call_args.args == ("USE SECONDARY ROLES NONE",)
        return catalog.tables["items"]

    monkeypatch.setattr("publishing.compile_table", compile_one)
    result = compile_catalog(conn, config, Deployment.load())
    assert result.reader_role == catalog.reader_role


def test_reader_rotation_and_legacy_receipt(tmp_path, catalog):
    dep = Deployment.load()
    previous = catalog.model_copy(update={"reader_role": "OLD_READER"})
    legacy = tmp_path / "v1/app/catalog.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(previous.model_dump_json(exclude={"reader_role"}))
    (legacy.parent.parent / "share.sql").write_text(
        f'GRANT USAGE ON APPLICATION SERVICE {dep.service} TO ROLE "OLD_READER";\n'
    )
    receipt = tmp_path / "last-published.json"
    receipt.write_bytes(legacy.read_bytes())
    assert read_previous(legacy) == read_previous(receipt) == previous
    orphan = tmp_path / "export.json"
    orphan.write_bytes(legacy.read_bytes())
    with pytest.raises(ValueError, match="previous-reader"):
        read_previous(orphan)
    assert read_previous(orphan, "OLD_READER") == previous
    with pytest.raises(ValueError, match="conflicts"):
        read_previous(receipt, "UNRELATED_READER")
    release = build_release(catalog, dep, tmp_path / "v2", previous)
    assert read_previous(release / "app/catalog.json") == catalog
    share = (release / "share.sql").read_text()
    before, after = share.split("REVOKE USAGE ON APPLICATION SERVICE")
    assert f'TO ROLE "{dep.reader_role}"' in before and 'FROM ROLE "OLD_READER"' in after
    retire = (release / "retire-reader-grants.sql").read_text()
    for kind in ["DATABASE", "WAREHOUSE"]:
        assert f"REVOKE USAGE ON {kind}" in retire
    for path in release.glob("*.sql"):
        if path.stat().st_size:
            assert "USE SECONDARY ROLES NONE" in path.read_text()
            assert "Wrong Snowflake deployment account" in path.read_text()
    assert (release / "retire-caller-grants.sql").read_text() == ""
    assert "SHOW GRANTS ON ACCOUNT" in retire and "SHOW ROLES LIKE" in retire
    assert "SHOW DATABASES LIKE" in retire and "SHOW WAREHOUSES LIKE" in retire
    assert 'WHERE "owner" = CURRENT_ROLE()' in share
    assert '"DB"."APP"."R&D"' in (release / "caller-grants.sql").read_text()


def test_removed_grant_is_only_skipped_after_complete_inventory(catalog):
    old = catalog.model_copy(
        update={
            "tables": {
                "items": catalog.tables["items"].model_copy(
                    update={"source": ("DB", "APP", "old'$$")}
                )
            }
        }
    )
    sql = grants_sql(catalog, old, retire=True)
    assert (
        sql.index("REVOKE CALLER SELECT")
        < sql.index("IF (SQLCODE <> 2003)")
        < sql.index("SHOW CALLER GRANTS TO ROLE")
    )
    assert "MANAGE GRANTS" in sql and 'IS_ROLE_IN_SESSION("grantee_name")' in sql
    assert 'OR "name" NOT IN' in sql and "rows_seen >= 10000" in sql


@pytest.mark.parametrize("new_versions", [set(), {"VERSION$2", "VERSION$3"}, {"LATEST"}])
def test_publish_refuses_ambiguous_build_before_promotion(
    tmp_path, catalog, monkeypatch, new_versions
):
    dep = Deployment.load()
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    release = build_release(catalog, dep, tmp_path / "release", None)
    monkeypatch.setattr(manage, "verified_account", lambda *args: catalog.account)
    monkeypatch.setattr(manage, "current_account", lambda *args: catalog.account)
    conn = MagicMock()
    monkeypatch.setattr("snowflake.connector.connect", lambda **kwargs: conn)
    monkeypatch.setattr(
        manage,
        "package_versions",
        MagicMock(side_effect=[{"VERSION$1"}, {"VERSION$1"} | new_versions]),
    )
    run = MagicMock()
    monkeypatch.setattr(manage, "snow", run)
    with pytest.raises(ValueError, match="immutable package version"):
        manage.publish("profile", dep, release)
    assert run.call_count == 3 and "--build-only" in run.call_args.args
    assert not any(
        "CREATE OR ALTER APPLICATION SERVICE" in c.args[0]
        for c in conn.cursor.return_value.execute.call_args_list
    )
    assert not (release / "published-artifact.json").exists()


def test_legacy_publish_uses_scoped_copy_and_records_exact_artifact(tmp_path, catalog, monkeypatch):
    dep = Deployment.load()
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    release = build_release(catalog, dep, tmp_path / "release", None)
    manifest_path = release / "app/app.yml"
    manifest = yaml.safe_load(manifest_path.read_text())
    del manifest["build_job_location"]
    original = yaml.safe_dump(manifest)
    manifest_path.write_text(original)
    monkeypatch.setattr(manage, "verified_account", lambda *args: catalog.account)
    monkeypatch.setattr(manage, "current_account", lambda *args: catalog.account)
    conn = MagicMock()
    monkeypatch.setattr("snowflake.connector.connect", lambda **kwargs: conn)
    monkeypatch.setattr(
        manage,
        "package_versions",
        MagicMock(side_effect=[{"VERSION$1"}, {"VERSION$1", "VERSION$2"}]),
    )
    phases = []

    def command(*args):
        scoped = Path(args[args.index("--project") + 1])
        assert scoped != manifest_path.parent
        scoped_manifest = yaml.safe_load((scoped / "app.yml").read_text())
        assert scoped_manifest["build_job_location"] == f"{dep.database_name}.API"
        assert scoped_manifest["code_stage"].startswith("SNOWFASTAPI_UPLOAD_")
        assert args[args.index("--account") + 1] == catalog.account
        phases.append(args[2] if args[1] == "deploy" else "validate")

    monkeypatch.setattr(manage, "snow", command)
    verify = MagicMock()
    monkeypatch.setattr(manage, "wait_for_service", verify)
    manage.publish("profile", dep, release)
    assert phases == ["validate", "--upload-only", "--build-only"]
    queries = [c.args[0] for c in conn.cursor.return_value.execute.call_args_list]
    assert queries[0] == "USE SECONDARY ROLES NONE"
    assert queries[1].startswith(f"CREATE STAGE {dep.database_name}.API.SNOWFASTAPI_UPLOAD_")
    assert (
        queries[2].startswith("DROP STAGE IF EXISTS")
        and queries[1].split()[2] == queries[2].split()[-1]
    )
    assert queries[3].startswith(f"CREATE OR ALTER APPLICATION SERVICE {dep.service}")
    assert (
        "VERSION VERSION$2 COMPUTE_RESOURCE = SERVERLESS" in queries[3]
        and "LATEST" not in queries[3]
    )
    assert yaml.safe_load(queries[3].split("$$")[1]) == {
        "health_check": "/healthz",
        "query_warehouse": dep.warehouse_name,
    }
    expected = manage.Artifact(
        f"{dep.database_name}.API.SNOWFASTAPI_REPO", "SNOWFASTAPI", "VERSION$2"
    )
    assert verify.call_args.args[1:] == (dep.service, expected)
    assert json.loads((release / "published-artifact.json").read_text()) == expected._asdict()
    assert manifest_path.read_text() == original


def test_split_publisher_obeys_combined_lock_before_building(tmp_path, catalog, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr(manage, "verified_account", lambda *args: catalog.account)
    with manage.publication_lock(catalog.account, catalog.service), pytest.raises(Timeout):
        manage.publish("profile", Deployment.load(), tmp_path / "unused")


@pytest.mark.parametrize("retained", [True, False])
def test_dcm_overlap_only_carries_existing_outgoing_grants(tmp_path, monkeypatch, retained):
    dep = Deployment.load()
    conn = MagicMock()
    monkeypatch.setattr(manage, "current_account", lambda *args: "TEST-ACCOUNT")
    monkeypatch.setattr(manage, "verified_account", lambda *args: "TEST-ACCOUNT")
    monkeypatch.setattr("snowflake.connector.connect", lambda **kwargs: conn)
    fields = ["granted_to", "grantee_name", "privilege"]
    rows = [("ROLE", "OLD_READER", "USAGE")] if retained else []
    db = MetaCursor(
        [
            ([], []),
            (["name", "owner"], [("API", dep.dcm_role)]),
            (fields, rows),
            (["name", "owner"], [("DEMO_PRODUCTS", dep.dcm_role)]),
            (fields, [("ROLE", "OTHER_READER", "SELECT")]),
        ]
    )
    conn.cursor.return_value = db

    def apply(profile, dep, account, project, apply):
        sql = project / "sources/definitions/reader-transition.sql"
        if retained:
            assert (
                sql.read_text()
                == f"GRANT USAGE ON SCHEMA {dep.database_name}.API TO ROLE OLD_READER;\n"
            )
            assert project != manage.ROOT / "dcm"
        else:
            assert not sql.exists() and project == manage.ROOT / "dcm"

    monkeypatch.setattr(manage, "run_infra", apply)
    assert manage.apply_infra("profile", dep, True, retain_reader="OLD_READER") is retained


@pytest.mark.parametrize("publish_succeeds", [False, True])
def test_combined_rotation_retires_only_after_pinned_publication(
    tmp_path, catalog, monkeypatch, publish_succeeds
):
    dep = Deployment.load()
    old = catalog.model_copy(update={"reader_role": "OUTGOING"})
    state = tmp_path / "build/deployments" / catalog.account / dep.service
    state.mkdir(parents=True)
    receipt = state / "last-published.json"
    receipt.write_text(old.model_dump_json())
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr(manage, "ROOT", tmp_path)
    monkeypatch.setattr(manage, "verified_account", lambda *args: catalog.account)
    events = []

    def infra(*args, retain_reader=None, **kwargs):
        events.append("DCM overlap" if retain_reader else "DCM cutover")
        return bool(retain_reader)

    def prepare(args, dep, release, previous, **kwargs):
        build_release(catalog, dep, release, read_previous(previous))

    def publish(*args):
        events.append("publish")
        if not publish_succeeds:
            raise ValueError("build failed")

    def run(cmd, **kwargs):
        if cmd[1:3] == ["app", "setup"]:
            return SimpleNamespace(stdout='{"serverless":true,"python-serverless":true}')
        assert cmd[:2] == ["snow", "sql"]
        assert cmd[cmd.index("--enable-templating") + 1] == "NONE"
        assert cmd[cmd.index("--secondary-roles") + 1] == "NONE"
        assert cmd[cmd.index("--account") + 1] == catalog.account
        events.append(Path(cmd[cmd.index("-f") + 1]).name)
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(manage, "apply_infra", infra)
    monkeypatch.setattr(manage, "prepare", prepare)
    monkeypatch.setattr(manage, "publish_release", publish)
    monkeypatch.setattr(manage.subprocess, "run", run)
    args = SimpleNamespace(
        connection="profile", previous=None, previous_reader=None, grant_role="ADMIN"
    )
    if publish_succeeds:
        manage.deploy(args, dep)
        assert read_previous(receipt) == catalog
        assert events[-3:] == ["share.sql", "DCM cutover", "retire-reader-grants.sql"]
    else:
        with pytest.raises(ValueError, match="build failed"):
            manage.deploy(args, dep)
        assert read_previous(receipt) == old
        assert events == ["DCM overlap", "publisher-grants.sql", "caller-grants.sql", "publish"]


def test_client_only_sends_session_credential_to_discovered_service(monkeypatch, capsys):
    import sys

    import client

    sf = MagicMock()
    db = sf.cursor.return_value
    db.description = [SimpleNamespace(name="url")]
    db.fetchone.return_value = ("demo.snowflake.app",)
    sf._rest._token_request.return_value = {"data": {"sessionToken": "temporary-test-session"}}
    monkeypatch.setattr("snowflake.connector.connect", MagicMock(return_value=sf))
    http = MagicMock()
    response = http.getresponse.return_value.__enter__.return_value
    response.status = 200
    response.getheader.return_value = "application/json"
    response.read.return_value = b'{"items":[],"next_cursor":null}'
    dial = MagicMock(return_value=http)
    monkeypatch.setattr(client, "HTTPSConnection", dial)
    monkeypatch.setattr(sys, "argv", ["client.py", "demo", "-c", "example", "--role", "READER"])
    client.main()
    assert dial.call_args.args == ("demo.snowflake.app",)
    assert (
        http.request.call_args.kwargs["headers"]["Authorization"]
        == 'Snowflake Token="temporary-test-session"'
    )
    assert "temporary-test-session" not in capsys.readouterr().out
    sf.close.assert_called_once()
    db.fetchone.return_value = ("unrelated.example",)
    with pytest.raises(ValueError):
        client.main()
    assert dial.call_count == 1
