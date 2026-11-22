"""Opt-in checks of Snowflake SQL, deployment privileges, and the hosted HTTPS client."""

import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from contextlib import closing
from http.client import HTTPSConnection
from urllib.parse import urlsplit

import pytest
import snowflake.connector
import uvicorn

from app.snowapi.api import create_app
from app.snowapi.catalog import Column, Dataset
from app.snowapi.paging import make_page
from client import service_origin
from publishing import ROOT, Deployment, compile_catalog, metadata

PROFILE = os.getenv("SNOWFASTAPI_TEST_CONNECTION")
CHANNEL = os.getenv("SNOWFASTAPI_TEST_BROWSER", "chromium")
pytestmark = pytest.mark.skipif(
    not PROFILE, reason="set SNOWFASTAPI_TEST_CONNECTION for warehouse smoke"
)


def test_python_client_against_live_sample_data(tmp_path):
    profile_options = {
        "connection_name": PROFILE,
        "paramstyle": "qmark",
        "session_parameters": {
            "QUERY_TAG": "SnowFastAPI:warehouse-smoke",
            "STATEMENT_TIMEOUT_IN_SECONDS": 30,
        },
    }
    if role := os.getenv("SNOWFASTAPI_TEST_ROLE"):
        profile_options["role"] = role
    config = tmp_path / "tables.toml"
    config.write_text(
        '[tables.regions]\ntable="SNOWFLAKE_SAMPLE_DATA.TPCH_SF1.REGION"\n'
        'key=["R_REGIONKEY"]\ncolumns=["R_REGIONKEY","R_NAME"]\nmax_page_size=3\n'
    )
    with closing(snowflake.connector.connect(**profile_options)) as conn:
        with closing(conn.cursor()) as db:
            db.execute("SELECT CURRENT_WAREHOUSE()")
            warehouse = db.fetchone()[0]
        deployment = Deployment.load().model_copy(update={"warehouse_name": warehouse})
        catalog = compile_catalog(conn, config, deployment)

    def connect(token, selected_warehouse):
        assert token == "loopback-fixture" and selected_warehouse == warehouse
        return snowflake.connector.connect(**profile_options)

    api = create_app(catalog, connect)

    @api.middleware("http")
    async def fixture_ingress(request, call_next):
        request.scope["headers"] = [
            *request.scope["headers"],
            (b"sf-context-current-user-token", b"loopback-fixture"),
        ]
        return await call_next(request)

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(api, log_level="error", access_log=False))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started and time.monotonic() < deadline:
                time.sleep(0.02)
            assert server.started
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "client.py"),
                    f"http://127.0.0.1:{port}",
                    "regions",
                    "--limit",
                    "2",
                    "--pages",
                    "3",
                    "--channel",
                    CHANNEL,
                    "--headless",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            pages = [json.loads(line) for line in result.stdout.splitlines()]
            assert [len(p["items"]) for p in pages] == [2, 2, 1]
            assert [row["R_REGIONKEY"] for p in pages for row in p["items"]] == list(range(5))
            assert pages[-1]["next_cursor"] is None
        finally:
            server.should_exit = True
            thread.join(timeout=10)


@pytest.mark.skipif(
    os.getenv("SNOWFASTAPI_TEST_DEV") != "1",
    reason="set SNOWFASTAPI_TEST_DEV=1 with the DEV bootstrap",
)
def test_deployed_demo_roles_and_table_only_onboarding():
    from uuid import uuid4

    from app.snowapi.paging import decode_cursor, page_query
    from publishing import TableSpec, compile_table

    dep = Deployment.load()

    def connect(role):
        return snowflake.connector.connect(
            connection_name=PROFILE,
            role=role,
            warehouse=dep.warehouse_name,
            paramstyle="qmark",
            session_parameters={"QUERY_TAG": "SnowFastAPI:dev-smoke"},
        )

    table_name = f"{dep.database_name}.API.DEMO_PRODUCTS"
    with closing(connect(dep.reader_role)) as conn, closing(conn.cursor()) as db:
        db.execute("USE SECONDARY ROLES NONE")
        db.execute(f"SELECT ID FROM {table_name} ORDER BY ID")
        assert [row[0] for row in db] == [1, 2, 3, 4, 5]
    with closing(connect(dep.app_owner)) as conn, closing(conn.cursor()) as db:
        db.execute("USE SECONDARY ROLES NONE")
        with pytest.raises(snowflake.connector.ProgrammingError) as denied:
            db.execute(f"SELECT ID FROM {table_name} LIMIT 1")
        assert denied.value.errno in {2003, 3001} or denied.value.sqlstate == "42501"
    with closing(connect(dep.dcm_role)) as conn, closing(conn.cursor()) as db:
        db.execute("USE SECONDARY ROLES NONE")
        name = dep.database_name + ".API.PAGING_TEST_" + uuid4().hex.upper()
        # A session-scoped fixture exercises real composite PK metadata and Snowflake collation.
        db.execute(
            f"CREATE TEMPORARY TABLE {name} (CODE VARCHAR(16) COLLATE 'en-ci' NOT NULL, "
            "ID NUMBER(38,0) NOT NULL, PRIMARY KEY (CODE, ID))"
        )
        huge = 10**37
        db.execute(f"INSERT INTO {name} VALUES ('A', 1), ('a', 2), ('a', {huge}), ('b', 3)")
        table = compile_table(db, TableSpec(table=name, max_page_size=2), dep.database_name)
        assert table.key == ("CODE", "ID")
        key = table.fingerprint("example")

        def read(after):
            sql, binds = page_query(table, after, 2)
            db.execute(sql, binds)
            return make_page(table, key, db, 2)

        first = read(None)
        second = read(decode_cursor(first["next_cursor"], key, table.key_columns))
        assert first["items"] + second["items"] == [
            {"CODE": "A", "ID": 1},
            {"CODE": "a", "ID": 2},
            {"CODE": "a", "ID": str(huge)},
            {"CODE": "b", "ID": 3},
        ]
        assert second["next_cursor"] is None


@pytest.mark.skipif(
    os.getenv("SNOWFASTAPI_TEST_DEV") != "1",
    reason="set SNOWFASTAPI_TEST_DEV=1 with the DEV bootstrap",
)
def test_dev_interval_and_map_projection():
    dep = Deployment.load()
    dataset = Dataset(
        source=(dep.database_name, "API", "INTERVAL_MAP_FIXTURE"),
        kind="view",
        key=("ID",),
        columns=(
            Column(name="ID", sql_type="NUMBER(38,0)"),
            Column(name="DURATION", sql_type="INTERVAL DAY(2) TO SECOND(9)"),
            Column(name="TENURE", sql_type="INTERVAL YEAR(2) TO MONTH"),
            Column(name="COUNTS", sql_type="MAP(NUMBER(38,0), VARCHAR)"),
        ),
    )
    projection = ", ".join(column.projection_sql for column in dataset.columns)
    with (
        closing(
            snowflake.connector.connect(
                connection_name=PROFILE,
                role=dep.reader_role,
                warehouse=dep.warehouse_name,
                session_parameters={
                    "QUERY_TAG": "SnowFastAPI:dev-types",
                    "STATEMENT_TIMEOUT_IN_SECONDS": 30,
                },
            )
        ) as conn,
        closing(conn.cursor()) as db,
    ):
        db.execute("USE SECONDARY ROLES NONE")
        db.execute(
            "WITH INTERVAL_MAP_FIXTURE AS (SELECT 1 AS ID, "
            "INTERVAL '0 00:00:09.123456789' DAY(2) TO SECOND(9) AS DURATION, "
            "INTERVAL '-1-08' YEAR(2) TO MONTH AS TENURE, "
            "OBJECT_CONSTRUCT('42', 'west', '-7', 'east')::MAP(NUMBER(38,0), VARCHAR) AS COUNTS) "
            f"SELECT {projection} FROM INTERVAL_MAP_FIXTURE"
        )
        page = make_page(dataset, dataset.fingerprint("types"), db, 1)
    assert page["next_cursor"] is None
    (row,) = page["items"]
    assert row["ID"] == 1 and re.fullmatch(r"\+0+ 00:00:09\.123456789", row["DURATION"])
    assert re.fullmatch(r"-0*1-08", row["TENURE"])
    assert row["COUNTS"] == {"42": "west", "-7": "east"}


def hosted_demo_maximum(dep):
    with (
        closing(
            snowflake.connector.connect(
                connection_name=PROFILE, role=dep.reader_role, paramstyle="qmark"
            )
        ) as conn,
        closing(conn.cursor()) as db,
    ):
        db.execute("USE SECONDARY ROLES NONE")
        db.execute("DESCRIBE APPLICATION SERVICE IDENTIFIER(?)", (dep.service,))
        (service,) = metadata(db)
        origin = urlsplit(service_origin("https://" + service["url"].removeprefix("https://")))
        assert (
            origin.hostname
            and origin.hostname.endswith(".snowflake.app")
            and origin.port in (None, 443)
        )
        with closing(HTTPSConnection(origin.hostname, timeout=60)) as https:
            token = conn._rest._token_request("ISSUE")["data"]["sessionToken"]
            https.request(
                "GET", "/openapi.json", headers={"Authorization": f'Snowflake Token="{token}"'}
            )
            with https.getresponse() as response:
                assert response.status == 200
                operation = json.load(response)["paths"]["/v1/tables/demo"]["get"]
    (limit,) = (p for p in operation["parameters"] if p["in"] == "query" and p["name"] == "limit")
    ceiling = limit["schema"]["maximum"]
    assert isinstance(ceiling, int) and ceiling >= 1
    return ceiling


@pytest.mark.skipif(
    os.getenv("SNOWFASTAPI_TEST_HOSTED") != "1",
    reason="set SNOWFASTAPI_TEST_HOSTED=1 for a deployed service",
)
def test_hosted_native_connection_client():
    dep = Deployment.load()
    ceiling = hosted_demo_maximum(dep)
    limit = min(2, ceiling)
    command = [
        sys.executable,
        str(ROOT / "client.py"),
        "demo",
        "-c",
        PROFILE,
        "--service",
        dep.service,
        "--role",
        dep.reader_role,
    ]

    def run(*flags):
        return subprocess.run([*command, *flags], capture_output=True, text=True, timeout=120)

    def read(*flags):
        result = run(*flags)
        assert result.returncode == 0, result.stderr
        return [json.loads(line) for line in result.stdout.splitlines()]

    (first,) = read("--limit", str(limit), "--pages", "1")
    assert first["next_cursor"]
    # The first process has exited and its connector session is closed before resuming.
    rest = read("--limit", str(limit), "--pages", "5", "--cursor", first["next_cursor"])
    pages = [first, *rest]
    assert [len(page["items"]) for page in pages] == [min(limit, 5 - i) for i in range(0, 5, limit)]
    assert [row["ID"] for page in pages for row in page["items"]] == [1, 2, 3, 4, 5]
    assert pages[-1]["next_cursor"] is None
    if ceiling > limit:
        (at_limit,) = read("--limit", str(ceiling), "--pages", "1")
        assert len(at_limit["items"]) == min(5, ceiling)
    over_limit = run("--limit", str(ceiling + 1), "--pages", "1")
    assert over_limit.returncode != 0 and "HTTP 422" in over_limit.stderr
