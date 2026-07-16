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
    assert all(o.name.startswith(("procrastinate_", "idx_procrastinate_")) for o in objs)


def test_every_create_statement_in_the_bundled_schema_is_covered():
    """Drift guard: independently extract every top-level CREATE statement
    name from procrastinate's bundled schema.sql and require each one to
    appear in the declared list. If procrastinate adds an object of a kind
    the parser can't classify, parse_schema_sql raises instead, either
    way, a stale/partial list is impossible to ship silently."""
    from procrastinate import schema as procrastinate_schema

    sql = procrastinate_schema.SchemaManager.get_schema()
    declared = {o.name for o in ProcrastinateJobProvider().owned_schema_objects()}

    statement_names = re.findall(
        r"^CREATE\s+(?:OR\s+REPLACE\s+)?(?:UNIQUE\s+)?"
        r"(?:TABLE|TYPE|FUNCTION|INDEX|TRIGGER|SEQUENCE)\s+"
        r"(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_][A-Za-z0-9_$]*)",
        sql,
        flags=re.MULTILINE | re.IGNORECASE,
    )
    assert statement_names, "bundled schema.sql yielded no CREATE statements"
    missing = set(statement_names) - declared
    assert not missing, f"objects in procrastinate's schema missing from the declared list: {missing}"

    n_create_lines = len(re.findall(r"^CREATE\b", sql, flags=re.MULTILINE))
    assert len(statement_names) == n_create_lines, (
        "some top-level CREATE statements were not matched by the guard regex"
    )


def test_missing_procrastinate_package_fails_naming_the_extra(monkeypatch):
    """No partial/silent output when the optional dependency is absent:
    the enumeration must fail loudly with the install hint."""
    monkeypatch.setitem(sys.modules, "procrastinate", None)
    with pytest.raises(RuntimeError, match=r"fymo\[procrastinate\]"):
        ProcrastinateJobProvider().owned_schema_objects()
