import base64
import binascii
import json
import math
import re
from collections.abc import Iterable
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from .catalog import Column, Dataset

MAX_CURSOR = 8192
MAX_TEXT_KEY_BYTES = 192
MAX_PAGE_BYTES = 4 * 1024 * 1024


class BadCursor(ValueError):
    """The supplied bookmark doesn't match this route and its key types."""


class DataContractError(ValueError):
    """Returned data no longer meets the published paging contract."""


class PageTooLarge(ValueError):
    """The requested rows exceed the response byte budget."""


def valid_key(value: object, column: Column) -> bool:
    if not isinstance(value, str):
        return False
    if column.key_type == "integer":
        return bool(re.fullmatch(r"0|-?[1-9][0-9]{0,37}", value))
    if column.key_type == "date":
        try:
            return date.fromisoformat(value).isoformat() == value
        except ValueError:
            return False
    return len(value.encode("utf-8")) <= MAX_TEXT_KEY_BYTES


def decode_cursor(token: str, fingerprint: str, columns: tuple[Column, ...]) -> list[str]:
    try:
        if len(token) > MAX_CURSOR or not re.fullmatch(r"[A-Za-z0-9_-]+", token):
            raise BadCursor
        raw = base64.b64decode(token + "=" * (-len(token) % 4), altchars=b"-_", validate=True)
        payload = json.loads(raw)
        if not isinstance(payload, list) or len(payload) != 2 or payload[0] != fingerprint:
            raise BadCursor
        values = payload[1]
        if not isinstance(values, list) or len(values) != len(columns):
            raise BadCursor
        if not all(valid_key(v, c) for v, c in zip(values, columns, strict=True)):
            raise BadCursor
        return values
    except (ValueError, UnicodeError, RecursionError, binascii.Error) as error:
        raise BadCursor from error


def encode_cursor(fingerprint: str, values: tuple[str, ...]) -> str:
    raw = json.dumps([fingerprint, values], ensure_ascii=False, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def page_query(dataset: Dataset, after: list[str] | None, size: int) -> tuple[str, list]:
    keys = dataset.key_columns
    order = ", ".join(f"{column.ordered_sql} ASC NULLS FIRST" for column in keys)
    projection = ", ".join(column.projection_sql for column in dataset.columns)
    predicates, binds = [], []
    if after is not None:
        casts = {
            "integer": "?::NUMBER(38,0)",
            "date": "TO_DATE(?, 'YYYY-MM-DD')",
            "text": "COLLATE(?::VARCHAR, 'utf8')",
        }
        for end in range(len(keys)):
            terms = []
            for index in range(end + 1):
                key = keys[index]
                op = ">" if index == end else "="
                terms.append(f"{key.ordered_sql} {op} {casts[key.key_type]}")
                binds.append(after[index])
            predicates.append("(" + " AND ".join(terms) + ")")
    where = " WHERE " + " OR ".join(predicates) if predicates else ""
    binds.append(size + 1)
    return f"SELECT {projection} FROM {dataset.qualified}{where} ORDER BY {order} LIMIT ?", binds


def json_value(value):
    if isinstance(value, timedelta):
        # A connector-native duration (e.g. inside a structured value) has microsecond precision.
        duration = abs(value)
        hours, remaining = divmod(duration.seconds, 3600)
        minutes, seconds = divmod(remaining, 60)
        sign = "-" if value.days < 0 else "+"
        return (
            f"{sign}{duration.days} {hours:02}:{minutes:02}:{seconds:02}.{duration.microseconds:06}"
        )
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, int) and abs(value) > 2**53 - 1:
        return str(value)
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return base64.b64encode(value).decode()
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    if isinstance(value, dict):
        # Snowflake MAP keys have a single SQL type, either text or scale-zero integers.
        return {
            str(int(k)) if isinstance(k, Decimal) else str(k): json_value(v)
            for k, v in value.items()
        }
    return value


def key_position(value, column: Column) -> str:
    if column.key_type == "integer":
        if type(value) is int:
            result = str(value)
        elif (
            isinstance(value, Decimal) and value.is_finite() and value == value.to_integral_value()
        ):
            result = str(int(value))
        else:
            raise DataContractError
    elif column.key_type == "date" and isinstance(value, date) and not isinstance(value, datetime):
        result = value.isoformat()
    elif column.key_type == "text" and isinstance(value, str):
        result = value
    else:
        raise DataContractError
    if not valid_key(result, column):
        raise DataContractError
    return result


def make_page(dataset: Dataset, fingerprint: str, rows: Iterable, size: int):
    items = []
    total_bytes = 0
    previous = None
    next_cursor = None
    indexes = {column.name: i for i, column in enumerate(dataset.columns)}
    for row in rows:
        position = tuple(key_position(row[indexes[c.name]], c) for c in dataset.key_columns)
        if position == previous:
            raise DataContractError
        if len(items) == size:
            assert previous is not None
            next_cursor = encode_cursor(fingerprint, previous)
            break
        previous = position
        item = {}
        for column, value in zip(dataset.columns, row, strict=True):
            if isinstance(value, str) and column.sql_type.partition("(")[0] in {
                "VARIANT",
                "OBJECT",
                "ARRAY",
                "MAP",
            }:
                try:
                    value = json.loads(value, parse_float=Decimal)
                except json.JSONDecodeError:
                    # Snowflake also represents sparse/SQL NULL array elements as bare undefined.
                    pass
            item[column.name] = json_value(value)
        total_bytes += len(json.dumps(item, ensure_ascii=False, separators=(",", ":")).encode())
        if total_bytes > MAX_PAGE_BYTES:
            raise PageTooLarge
        items.append(item)
    return {"items": items, "next_cursor": next_cursor}
