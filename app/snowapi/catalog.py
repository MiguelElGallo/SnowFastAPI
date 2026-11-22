import hashlib
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

PAGE_CEILING = 1000
Name = Annotated[str, Field(min_length=1, max_length=255)]
Alias = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,62}$")]
PageSize = Annotated[StrictInt, Field(ge=1, le=PAGE_CEILING)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def quoted(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


class Column(Model):
    name: Name
    sql_type: str

    @property
    def key_type(self) -> str:
        if re.fullmatch(r"NUMBER\(\d+,0\)", self.sql_type):
            return "integer"
        if re.match(r"^(VARCHAR|CHAR|TEXT|STRING)\b", self.sql_type):
            return "text"
        if self.sql_type == "DATE":
            return "date"
        raise ValueError(f"{self.name} has unsupported pagination type {self.sql_type}")

    @property
    def ordered_sql(self) -> str:
        name = quoted(self.name)
        return f"COLLATE({name}, 'utf8')" if self.key_type == "text" else name

    @property
    def projection_sql(self) -> str:
        name = quoted(self.name)
        base = self.sql_type.partition("(")[0]
        formats = {
            "TIMESTAMP_NTZ": 'YYYY-MM-DD"T"HH24:MI:SS.FF9',
            "TIMESTAMP_TZ": 'YYYY-MM-DD"T"HH24:MI:SS.FF9TZH:TZM',
            "TIMESTAMP_LTZ": 'YYYY-MM-DD"T"HH24:MI:SS.FF9TZH:TZM',
            "TIME": "HH24:MI:SS.FF9",
        }
        if base in formats:
            return f"TO_CHAR({name}, '{formats[base]}') AS {name}"
        if self.sql_type.startswith("INTERVAL"):
            # Preserve the declared interval fields and nanoseconds before connector conversion.
            return f"TO_VARCHAR({name}) AS {name}"
        return name


class Dataset(Model):
    source: tuple[Name, Name, Name]
    kind: Literal["table", "view"]
    columns: Annotated[tuple[Column, ...], Field(min_length=1)]
    key: Annotated[tuple[Name, ...], Field(min_length=1, max_length=4)]
    max_page_size: PageSize = 100

    @model_validator(mode="after")
    def validate_columns(self):
        names = [c.name for c in self.columns]
        if len(names) != len(set(names)) or len(self.key) != len(set(self.key)):
            raise ValueError("Duplicate column in projection or pagination key")
        if not set(self.key).issubset(names):
            raise ValueError("Include every pagination key column in the projection")
        for col in self.key_columns:
            _ = col.key_type
        return self

    @property
    def key_columns(self) -> tuple[Column, ...]:
        columns = {col.name: col for col in self.columns}
        return tuple(columns[name] for name in self.key)

    @property
    def qualified(self) -> str:
        return ".".join(map(quoted, self.source))

    def fingerprint(self, route: str) -> str:
        definition = route + "\n" + self.model_dump_json()
        return hashlib.sha256(definition.encode()).hexdigest()[:24]


class Catalog(Model):
    version: Literal[1] = 1
    account: str
    service: str
    owner: Name
    warehouse: Name
    reader_role: Name | None = None
    tables: Annotated[dict[Alias, Dataset], Field(min_length=1)]
