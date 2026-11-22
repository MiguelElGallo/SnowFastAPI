import re
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from snowflake.connector.errors import ProgrammingError

from app.snowapi.api import create_app
from app.snowapi.catalog import Catalog, Column, Dataset
from app.snowapi.paging import (
    BadCursor,
    DataContractError,
    decode_cursor,
    encode_cursor,
    make_page,
    page_query,
)


@pytest.fixture
def dataset():
    return Dataset(
        source=("DB", "API", "DEMO"),
        kind="view",
        columns=(
            Column(name="ID", sql_type="NUMBER(38,0)"),
            Column(name="NAME", sql_type="VARCHAR(20)"),
        ),
        key=("ID",),
        max_page_size=3,
    )


def service(dataset, results=()):
    catalog = Catalog(
        account="TEST-ACCOUNT",
        service="DB.API.APP",
        owner="OWNER",
        warehouse="WH",
        tables={"demo": dataset, "other": dataset},
    )
    connect = MagicMock()
    for_result = iter(results)

    def new_connection(token, warehouse):
        connection = MagicMock()
        db = connection.cursor.return_value
        db.__iter__.return_value = next(for_result)
        return connection

    connect.side_effect = new_connection
    return TestClient(create_app(catalog, connect)), connect


HEADERS = {"Sf-Context-Current-User-Token": "unit-test-caller"}


def test_cold_start_and_keyset(dataset):
    first_app, first_connect = service(dataset, [[(1, "a"), (2, "b"), (3, "c")]])
    page1 = first_app.get("/v1/tables/demo?limit=2", headers=HEADERS)
    assert page1.status_code == 200 and page1.headers["cache-control"] == "private, no-store"
    assert [item["ID"] for item in page1.json()["items"]] == [1, 2]
    first_connect.assert_called_once_with("unit-test-caller", "WH")

    app, connect = service(dataset, [[(3, "c")]])
    cursor = page1.json()["next_cursor"]
    page2 = app.get("/v1/tables/demo", params={"limit": 2, "cursor": cursor}, headers=HEADERS)
    assert page2.json() == {"items": [{"ID": 3, "NAME": "c"}], "next_cursor": None}
    assert connect.call_count == 1
    assert (
        app.get("/v1/tables/other", params={"cursor": cursor}, headers=HEADERS).status_code == 400
    )
    assert connect.call_count == 1
    vals = decode_cursor(cursor, dataset.fingerprint("demo"), dataset.key_columns)
    sql, params = page_query(dataset, vals, 2)
    assert params == ["2", 3] and 'WHERE ("ID" > ?::NUMBER(38,0))' in sql


def test_request_isolation_and_cleanup(dataset):
    catalog = Catalog(
        account="TEST-ACCOUNT",
        service="DB.API.APP",
        owner="OWNER",
        warehouse="WH",
        tables={"demo": dataset},
    )
    a, b = MagicMock(), MagicMock()
    a.cursor.return_value.__iter__.return_value = [(1, "visible to A"), (2, "A")]
    b.cursor.return_value.__iter__.return_value = []
    factory = MagicMock(side_effect=[a, b])
    client = TestClient(create_app(catalog, factory))
    p1 = client.get("/v1/tables/demo?limit=1", headers=HEADERS).json()
    p2 = client.get(
        "/v1/tables/demo",
        params={"cursor": p1["next_cursor"]},
        headers={"Sf-Context-Current-User-Token": "other-reader"},
    ).json()
    assert p2 == {"items": [], "next_cursor": None}
    assert [c.args[0] for c in factory.call_args_list] == ["unit-test-caller", "other-reader"]
    for connection in (a, b):
        connection.close.assert_called_once()
        connection.cursor.return_value.close.assert_called_once()


@pytest.mark.parametrize(
    ("path", "headers", "status"),
    [
        ("/healthz", {}, 200),
        ("/openapi.json", {}, 200),
        ("/v1/tables/demo", {}, 401),
        ("/v1/tables/demo", {"Authorization": "Bearer local-test"}, 401),
        ("/v1/tables/missing", HEADERS, 404),
        ("/v1/tables/demo?limit=4", HEADERS, 422),
        ("/v1/tables/demo?limit=0", HEADERS, 422),
        ("/v1/tables/demo?cursor=bad", HEADERS, 400),
    ],
)
def test_request_boundaries(dataset, path, headers, status):
    app, connect = service(dataset)
    assert app.get(path, headers=headers).status_code == status
    connect.assert_not_called()


def test_snowflake_error_is_sanitized(dataset):
    app, connect = service(dataset)
    connect.side_effect = ProgrammingError(msg="sensitive-message", errno=3001, sqlstate="42501")
    response = app.get("/v1/tables/demo", headers=HEADERS)
    assert response.status_code == 403 and "sensitive-message" not in response.text
    assert connect.call_count == 1


def test_published_errors_and_same_origin_swagger(dataset):
    api, connect = service(dataset)
    schema = api.get("/openapi.json").json()
    route = schema["paths"]["/v1/tables/demo"]["get"]
    assert route["x-snowflake-authentication"]["enforcedBy"] == "Snowflake App Runtime gateway"
    expected = {"400", "401", "403", "409", "413", "422", "429", "500", "503", "504"}
    assert set(route["responses"]) == {"200", *expected}
    for code in expected:
        error_schema = route["responses"][code]["content"]["application/json"]["schema"]
        assert error_schema["$ref"] == "#/components/schemas/ErrorResponse"
    assert (
        schema["components"]["schemas"]["ErrorResponse"]["properties"]["detail"]["type"] == "string"
    )
    assert isinstance(api.get("/v1/tables/demo?limit=0", headers=HEADERS).json()["detail"], str)
    assert "Retry-After" in route["responses"]["429"]["headers"]
    html = api.get("/docs").text
    assets = re.findall(r'(?:href|src)="([^"]+)"', html)
    assert len(assets) == 4 and all(path.startswith("/docs/") for path in assets)
    assert html.count("<script") == html.count('defer src="')
    for path in assets:
        assert api.get(path).status_code == 200
    initializer = api.get("/docs/initialize.js").text
    assert 'url: "/openapi.json"' in initializer and "validatorUrl: null" in initializer
    connect.assert_not_called()


@pytest.mark.parametrize(
    ("errno", "sqlstate", "detail"),
    [
        (630, None, "Snowflake query timed out"),
        (604, "57014", "Snowflake query was canceled or timed out"),
        (None, "57014", "Snowflake query was canceled or timed out"),
    ],
)
def test_query_timeout_responses(dataset, errno, sqlstate, detail):
    api, connect = service(dataset)
    connect.side_effect = ProgrammingError(msg="private query", errno=errno, sqlstate=sqlstate)
    result = api.get("/v1/tables/demo", headers=HEADERS)
    assert result.status_code == 504 and result.json() == {"detail": detail}


def test_unexpected_error_uses_private_json_response(dataset):
    api, connect = service(dataset)
    connect.side_effect = RuntimeError("private row")
    response = TestClient(api.app, raise_server_exceptions=False).get(
        "/v1/tables/demo", headers=HEADERS
    )
    assert response.status_code == 500 and response.headers["cache-control"] == "private, no-store"
    assert response.json() == {"detail": "The service could not complete this request."}


@pytest.mark.parametrize("bad", [None, 1, [], False, "01", "-0", "9" * 39])
def test_invalid_numeric_cursor(dataset, bad):
    token = encode_cursor("f", (bad,))
    with pytest.raises(BadCursor):
        decode_cursor(token, "f", dataset.key_columns)


def test_composite_order_and_precision():
    dataset = Dataset(
        source=("D", "S", "T"),
        kind="table",
        max_page_size=10,
        columns=[
            Column(name="DAY", sql_type="DATE"),
            Column(name="CODE", sql_type="VARCHAR(10)"),
            Column(name="ID", sql_type="NUMBER(38,0)"),
            Column(name="AMOUNT", sql_type="NUMBER(38,5)"),
        ],
        key=("DAY", "CODE", "ID"),
    )
    wide = 10**37
    day = date(2026, 3, 10)
    page = make_page(
        dataset, "f", [(day, "å", wide, Decimal("1.11200")), (day, "å", wide + 1, None)], 1
    )
    assert page["items"] == [
        {"DAY": "2026-03-10", "CODE": "å", "ID": str(wide), "AMOUNT": "1.11200"}
    ]
    values = decode_cursor(page["next_cursor"], "f", dataset.key_columns)
    sql, params = page_query(dataset, values, 1)
    assert params == [values[0], values[0], values[1], *values, 2]
    assert sql.count(" OR ") == 2 and "OFFSET" not in sql and "å" not in sql


@pytest.mark.parametrize("rows", [[(None, "bad")], [(1, "a"), (1, "b")]])
def test_dirty_key_at_boundary(dataset, rows):
    with pytest.raises(DataContractError):
        make_page(dataset, "f", rows, 1)


def test_changed_integer_key_type_fails(dataset):
    with pytest.raises(DataContractError):
        make_page(dataset, "f", [("10", "changed")], 1)


def test_intervals_and_structured_maps_survive_connector_conversions(dataset):
    interval = Column(name="DURATION", sql_type="INTERVAL DAY(3) TO SECOND(9)")
    year_month = Column(name="TENURE", sql_type="INTERVAL YEAR(3) TO MONTH")
    mapping = Column(name="COUNTS", sql_type="MAP(NUMBER(38,0), VARIANT)")
    published = dataset.model_copy(
        update={"columns": (dataset.columns[0], interval, year_month, mapping)}
    )
    sql, _ = page_query(published, None, 3)
    assert 'TO_VARCHAR("DURATION") AS "DURATION"' in sql
    assert 'TO_VARCHAR("TENURE") AS "TENURE"' in sql
    native_map = {Decimal("1E+2"): Decimal("1.250"), -1: 2**53}
    text_map = '{"100":1.250,"-1":9007199254740992}'
    api, _ = service(
        published,
        [
            [
                (1, "+0 00:00:09.123456789", "-1-08", text_map),
                (2, timedelta(microseconds=-1), "+2-11", native_map),
                (3, None, None, None),
            ]
        ],
    )
    response = api.get("/v1/tables/demo", headers=HEADERS)
    assert response.status_code == 200
    first, second, third = response.json()["items"]
    assert first["DURATION"] == "+0 00:00:09.123456789" and first["TENURE"] == "-1-08"
    assert second["DURATION"] == "-0 00:00:00.000001"
    assert first["COUNTS"] == second["COUNTS"] == {"100": "1.250", "-1": "9007199254740992"}
    assert third == {"ID": 3, "DURATION": None, "TENURE": None, "COUNTS": None}


def test_snowflake_semistructured_special_values_and_byte_limit(dataset, monkeypatch):
    variant = dataset.model_copy(
        update={"columns": (dataset.columns[0], Column(name="A", sql_type="ARRAY"))}
    )
    text = '[undefined, null, "undefined"]'
    assert make_page(variant, "f", [(1, text)], 1)["items"] == [{"ID": 1, "A": text}]
    assert make_page(variant, "f", [(1, '["undefined", null]')], 1)["items"][0]["A"] == [
        "undefined",
        None,
    ]
    monkeypatch.setattr("app.snowapi.paging.MAX_PAGE_BYTES", 10)
    app, _ = service(dataset, [[(1, "a long row")]])
    assert app.get("/v1/tables/demo", headers=HEADERS).status_code == 413


def test_connector_gets_only_current_gateway_token(monkeypatch):
    from app.snowapi.api import connect_caller

    factory = MagicMock()
    monkeypatch.setenv("SNOWFLAKE_ACCOUNT", "test-account")
    monkeypatch.setenv("SNOWFLAKE_HOST", "test-account.snowflakecomputing.com")
    monkeypatch.setattr("snowflake.connector.connect", factory)
    connect_caller("test-credential", "TEST_WH")
    args = factory.call_args.kwargs
    assert (args["authenticator"], args["token"], args["warehouse"]) == (
        "oauth",
        "test-credential",
        "TEST_WH",
    )
    assert not {"role", "password", "connection_name", "private_key"}.intersection(args)
