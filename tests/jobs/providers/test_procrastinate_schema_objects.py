"""ProcrastinateJobProvider.owned_schema_objects(), the declared list is
derived from the installed procrastinate's own bundled schema
(procrastinate.schema.SchemaManager.get_schema()), never hardcoded, so a
procrastinate upgrade that adds objects can't leave the list stale.
No database needed: the schema ships inside the package.
"""
import re
import sys

import pytest

from fymo.core.schema import SchemaObject
from fymo.jobs.providers.procrastinate import ProcrastinateJobProvider

_KIND_KEYWORDS = {
    "TABLE": "table",
    "TYPE": "type",
    "FUNCTION": "function",
    "SEQUENCE": "sequence",
    "INDEX": "index",
    "TRIGGER": "trigger",
    "VIEW": "view",
    "EXTENSION": "extension",
}

_MODIFIER_WORDS = {
    "OR", "REPLACE", "UNIQUE", "UNLOGGED", "MATERIALIZED", "CONCURRENTLY",
}


def _token_walk_created_objects(sql: str):
    """Independent extraction of every (kind, name) a DDL script creates.
    On purpose NOT the parser's mechanism: a flat token walk over the
    whole text (no anchors, no per-statement regexes), so the two cannot
    share a blind spot. Comments are dropped first; after that, every
    CREATE token must resolve to a kind keyword and a name or this
    helper fails the test."""
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    sql = re.sub(r"--[^\n]*", " ", sql)
    tokens = re.findall(r"[A-Za-z_][\w$]*", sql)
    found = []
    for i, token in enumerate(tokens):
        if token.upper() != "CREATE":
            continue
        j = i + 1
        while tokens[j].upper() in _MODIFIER_WORDS:
            j += 1
        kind_word = tokens[j].upper()
        assert kind_word in _KIND_KEYWORDS, (
            f"token walk hit a CREATE {kind_word} it cannot classify"
        )
        j += 1
        if tokens[j].upper() == "IF" and tokens[j + 1].upper() == "NOT":
            j += 3
        found.append((_KIND_KEYWORDS[kind_word], tokens[j]))
    return found


def test_enumerates_the_queue_tables():
    names = {
        o.name for o in ProcrastinateJobProvider().owned_schema_objects()
        if o.kind == "table"
    }
    assert {
        "procrastinate_jobs",
        "procrastinate_events",
        "procrastinate_periodic_defers",
        "procrastinate_workers",
    } <= names


def test_enumerates_types_functions_and_triggers():
    objs = ProcrastinateJobProvider().owned_schema_objects()
    kinds = {o.kind for o in objs}
    assert {"type", "table", "function", "index", "trigger", "sequence"} <= kinds
    assert all(isinstance(o, SchemaObject) for o in objs)
    assert all(
        o.name.startswith(("procrastinate_", "idx_procrastinate_"))
        for o in objs if o.kind != "extension"
    )


def test_the_do_block_guarded_extension_is_enumerated():
    """procrastinate 3.9.0's schema opens with an indented CREATE
    EXTENSION inside a DO $$ block. A line-anchored parser silently
    skipped it once (review finding on issue #51); it must show up."""
    assert SchemaObject(kind="extension", name="plpgsql") in (
        ProcrastinateJobProvider().owned_schema_objects()
    )


def test_every_create_token_in_the_bundled_schema_is_covered():
    """Drift guard: walk the raw bundled schema token by token, resolve
    every CREATE to a (kind, name), and require each one in the declared
    list. If a future procrastinate creates something the walk can't
    classify, the walk itself fails, so a stale or partial declared list
    can't survive an upgrade silently."""
    from procrastinate import schema as procrastinate_schema

    sql = procrastinate_schema.SchemaManager.get_schema()
    walked = _token_walk_created_objects(sql)
    assert walked, "bundled schema.sql yielded no CREATE statements"

    declared = {
        (o.kind, o.name)
        for o in ProcrastinateJobProvider().owned_schema_objects()
    }
    missing = set(walked) - declared
    assert not missing, (
        f"objects in procrastinate's schema missing from the declared list: {missing}"
    )


def test_missing_procrastinate_package_fails_naming_the_extra(monkeypatch):
    """No partial/silent output when the optional dependency is absent:
    the enumeration must fail loudly with the install hint."""
    monkeypatch.setitem(sys.modules, "procrastinate", None)
    with pytest.raises(RuntimeError, match=r"fymo\[procrastinate\]"):
        ProcrastinateJobProvider().owned_schema_objects()
