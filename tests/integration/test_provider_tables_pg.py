"""Cross-check `fymo schema provider-tables` against a real Postgres.

Applies procrastinate's bundled schema to the database TEST_DATABASE_URL
points at, then diffs the actual catalog (pg_class/pg_type/pg_proc/
pg_trigger) against what the command enumerates. This is the acceptance
proof for issue #51: an exclude list built from the command's output
protects every object procrastinate really created.

Skipped without TEST_DATABASE_URL, same gate as
tests/jobs/providers/test_procrastinate.py; point it at a throwaway
Postgres (the schema apply is not reversible here).
"""
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="needs TEST_DATABASE_URL pointing at a real Postgres instance",
)


@pytest.fixture
def database_url() -> str:
    return os.environ["TEST_DATABASE_URL"]


@pytest.fixture(autouse=True)
def _apply_schema(database_url):
    import procrastinate
    from procrastinate import exceptions, schema
    connector = procrastinate.SyncPsycopgConnector(conninfo=database_url)
    connector.open()
    try:
        schema.SchemaManager(connector).apply_schema()
    except exceptions.ConnectorException as e:
        if "already exists" not in str(e.__cause__):
            raise
    connector.close()


@pytest.fixture
def enumerated(tmp_path: Path, capsys):
    from fymo.cli.commands.schema import run_provider_tables

    (tmp_path / "fymo.yml").write_text(
        "name: catalog-check\njobs:\n  provider: procrastinate\n"
    )
    run_provider_tables(tmp_path)
    by_kind: dict = {}
    for line in capsys.readouterr().out.strip().splitlines():
        kind, _, name = line.partition(" ")
        by_kind.setdefault(kind, set()).add(name)
    return by_kind


def _catalog(database_url, query):
    import psycopg
    with psycopg.connect(database_url) as conn:
        return {row[0] for row in conn.execute(query)}


def test_every_procrastinate_table_in_the_catalog_is_enumerated(database_url, enumerated):
    tables = _catalog(
        database_url,
        "SELECT tablename FROM pg_tables"
        " WHERE schemaname = 'public' AND tablename LIKE 'procrastinate%'",
    )
    assert tables == enumerated["table"]


def test_every_procrastinate_function_in_the_catalog_is_enumerated(database_url, enumerated):
    functions = _catalog(
        database_url,
        "SELECT DISTINCT p.proname FROM pg_proc p"
        " JOIN pg_namespace n ON n.oid = p.pronamespace"
        " WHERE n.nspname = 'public' AND p.proname LIKE 'procrastinate%'",
    )
    assert functions == enumerated["function"]


def test_every_procrastinate_type_in_the_catalog_is_enumerated(database_url, enumerated):
    # Enums and standalone composite types only: every table also gets an
    # implicit row type in pg_type, which no schema tool manages separately.
    types = _catalog(
        database_url,
        "SELECT t.typname FROM pg_type t"
        " JOIN pg_namespace n ON n.oid = t.typnamespace"
        " LEFT JOIN pg_class c ON c.oid = t.typrelid"
        " WHERE n.nspname = 'public' AND t.typname LIKE 'procrastinate%'"
        " AND (t.typtype = 'e' OR (t.typtype = 'c' AND c.relkind = 'c'))",
    )
    assert types == enumerated["type"]


def test_every_procrastinate_sequence_in_the_catalog_is_enumerated(database_url, enumerated):
    sequences = _catalog(
        database_url,
        "SELECT c.relname FROM pg_class c"
        " JOIN pg_namespace n ON n.oid = c.relnamespace"
        " WHERE n.nspname = 'public' AND c.relkind = 'S'"
        " AND c.relname LIKE 'procrastinate%'",
    )
    assert sequences == enumerated["sequence"]


def test_every_explicit_procrastinate_index_in_the_catalog_is_enumerated(database_url, enumerated):
    # Equality after excluding constraint-backed indexes (pkeys, unique
    # constraints): those only exist through their table, no schema tool
    # manages them separately, and excluding the table already protects
    # them. Everything else on a procrastinate table must be enumerated,
    # so an under-reported explicit CREATE INDEX fails here.
    indexes = _catalog(
        database_url,
        "SELECT c.relname FROM pg_index i"
        " JOIN pg_class c ON c.oid = i.indexrelid"
        " JOIN pg_class t ON t.oid = i.indrelid"
        " JOIN pg_namespace n ON n.oid = t.relnamespace"
        " WHERE n.nspname = 'public' AND t.relname LIKE 'procrastinate%'"
        " AND NOT EXISTS ("
        "   SELECT 1 FROM pg_constraint con WHERE con.conindid = i.indexrelid"
        " )",
    )
    assert indexes == enumerated["index"]


def test_every_procrastinate_trigger_in_the_catalog_is_enumerated(database_url, enumerated):
    triggers = _catalog(
        database_url,
        "SELECT DISTINCT t.tgname FROM pg_trigger t WHERE NOT t.tgisinternal",
    )
    assert enumerated["trigger"] == {
        t for t in triggers if t.startswith("procrastinate")
    }


def test_enumerated_extensions_exist_in_the_catalog(database_url, enumerated):
    # Subset, not equality: the guarded CREATE EXTENSION plpgsql targets
    # an extension every Postgres already ships, and the catalog may hold
    # unrelated extensions the database had before the schema apply.
    extensions = _catalog(database_url, "SELECT extname FROM pg_extension")
    assert enumerated.get("extension", set()) <= extensions
