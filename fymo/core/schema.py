"""The owned-schema-objects seam (issue #51).

Some providers create real, permanent objects in the app's own database
(Procrastinate's queue tables being the canonical case). Declarative
schema diff tools only know the app's schema file, so those objects look
like strays and get proposed for DROP. This module is the seam that lets
anything holding a provider instance ask what it owns:

  * A provider declares its objects by implementing
    ``owned_schema_objects() -> tuple[SchemaObject, ...]``. The default on
    every provider base class returns ``()``, only providers that
    actually create database objects override it. The seam is duck-typed
    (see ``owned_schema_objects()`` below), so it isn't limited to job or
    broadcast providers: any future store or provider (e.g. an auth user
    store with its own tables) joins by defining the same method.
  * ``parse_schema_sql()`` derives the declaration from a library's
    bundled DDL text, so the list tracks whatever version is actually
    installed instead of drifting the way a hardcoded list would. It
    fails loudly on DDL it can't classify, a silently partial list would
    defeat the exclude lists built from it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Tuple

@dataclass(frozen=True)
class SchemaObject:
    """One database object a provider owns. `kind` is a lowercase word
    matching what schema diff tools manage as top-level objects: table,
    type, function, sequence, index, trigger, view, extension."""
    kind: str
    name: str


class SchemaParseError(Exception):
    """DDL text contained a CREATE statement the parser can't classify."""


def owned_schema_objects(provider) -> Tuple[SchemaObject, ...]:
    """The objects `provider` declares, or () when it declares nothing.

    Duck-typed on purpose: JobProvider/BroadcastProvider are
    runtime-checkable Protocols, and adding the method there would break
    isinstance() for existing custom providers that predate the seam."""
    declare = getattr(provider, "owned_schema_objects", None)
    if declare is None:
        return ()
    return tuple(declare())


# One regex per recognized statement head; group 1 is the object name.
# Matched at every CREATE token position, wherever it sits (indented,
# mid-line, inside a DO block), so nothing depends on line starts.
# UNIQUE INDEX collapses to "index", exclusion tooling doesn't care.
# CREATE EXTENSION is classified like everything else: procrastinate's
# schema opens with a guarded `CREATE EXTENSION IF NOT EXISTS plpgsql`
# inside a DO block, and enumerating it is harmless while ignoring it
# would need a silent-skip path this parser must not have.
_STATEMENT_RES = (
    ("table", re.compile(
        r"CREATE\s+(?:UNLOGGED\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_][\w$]*)",
        re.IGNORECASE)),
    ("type", re.compile(r"CREATE\s+TYPE\s+([A-Za-z_][\w$]*)", re.IGNORECASE)),
    ("function", re.compile(
        r"CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+([A-Za-z_][\w$]*)",
        re.IGNORECASE)),
    ("sequence", re.compile(
        r"CREATE\s+SEQUENCE\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_][\w$]*)",
        re.IGNORECASE)),
    ("index", re.compile(
        r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_][\w$]*)",
        re.IGNORECASE)),
    ("trigger", re.compile(
        r"CREATE\s+(?:OR\s+REPLACE\s+)?TRIGGER\s+([A-Za-z_][\w$]*)",
        re.IGNORECASE)),
    ("view", re.compile(
        r"CREATE\s+(?:OR\s+REPLACE\s+)?(?:MATERIALIZED\s+)?VIEW\s+([A-Za-z_][\w$]*)",
        re.IGNORECASE)),
    ("extension", re.compile(
        r"CREATE\s+EXTENSION\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_][\w$]*)",
        re.IGNORECASE)),
)

_COMMENT_RE = re.compile(r"/\*.*?\*/|--[^\n]*", re.DOTALL)
_CREATE_TOKEN_RE = re.compile(r"\bCREATE\b", re.IGNORECASE)

# A column whose type implicitly creates a `<table>_<column>_seq` sequence:
# serial family, or GENERATED ... AS IDENTITY.
_SERIAL_COLUMN_RE = re.compile(
    r"^\s*([A-Za-z_][\w$]*)\s+(?:big|small)?serial\b", re.IGNORECASE)
_IDENTITY_COLUMN_RE = re.compile(
    r"^\s*([A-Za-z_][\w$]*)\s+.*\bGENERATED\s+(?:ALWAYS|BY\s+DEFAULT)\s+AS\s+IDENTITY\b",
    re.IGNORECASE)


def parse_schema_sql(sql: str) -> Tuple[SchemaObject, ...]:
    """Extract every object a DDL script creates, in statement order.

    Comments are stripped, then EVERY remaining CREATE token in the text
    is visited: indented, mid-line, or nested inside a DO $$ block, each
    one is either classified into the output or raises SchemaParseError.
    Under-reporting is the one failure mode this parser is not allowed to
    have, so there is deliberately no code path that skips a CREATE.

    Tables contribute their implicit serial/identity sequences too, since
    schema tools that enumerate sequences would otherwise still propose
    dropping `<table>_id_seq`."""
    stripped = _COMMENT_RE.sub(" ", sql)
    objects = []
    seen = set()

    def add(kind: str, name: str) -> None:
        if (kind, name) not in seen:
            seen.add((kind, name))
            objects.append(SchemaObject(kind=kind, name=name))

    for match in _CREATE_TOKEN_RE.finditer(stripped):
        for kind, statement_re in _STATEMENT_RES:
            named = statement_re.match(stripped, match.start())
            if named:
                add(kind, named.group(1))
                if kind == "table":
                    for seq_name in _implicit_sequences(named.group(1), stripped, named.end(1)):
                        add("sequence", seq_name)
                break
        else:
            snippet = " ".join(stripped[match.start():match.start() + 60].split())
            raise SchemaParseError(
                f"unrecognized CREATE statement: {snippet!r}, "
                "fymo.core.schema.parse_schema_sql needs to learn this DDL form"
            )
    return tuple(objects)


def _implicit_sequences(table: str, sql: str, name_end: int):
    """Sequences Postgres creates for serial/identity columns of `table`,
    scanning the parenthesized column list that follows the table name."""
    open_paren = sql.find("(", name_end)
    if open_paren == -1:
        return
    depth = 1
    i = open_paren + 1
    while i < len(sql) and depth:
        if sql[i] == "(":
            depth += 1
        elif sql[i] == ")":
            depth -= 1
        i += 1
    for line in sql[open_paren + 1:i - 1].splitlines():
        column = _SERIAL_COLUMN_RE.match(line) or _IDENTITY_COLUMN_RE.match(line)
        if column:
            yield f"{table}_{column.group(1)}_seq"
