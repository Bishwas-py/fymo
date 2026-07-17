"""Tests for fymo.core.schema, the owned-schema-objects seam.

SchemaObject is the typed unit a provider uses to declare the database
objects it creates for itself (issue #51: schema diff tools propose
dropping provider tables because nothing enumerates them).
parse_schema_sql derives that list from a provider's bundled DDL text so
it can never drift from what the installed library actually creates.
"""
import pytest

from fymo.core.schema import (
    SchemaObject,
    SchemaParseError,
    owned_schema_objects,
    parse_schema_sql,
)


def test_parses_create_table():
    objs = parse_schema_sql("CREATE TABLE my_jobs (\n    id integer\n);")
    assert SchemaObject(kind="table", name="my_jobs") in objs


def test_parses_create_type():
    sql = "CREATE TYPE my_status AS ENUM ('todo', 'done');"
    assert parse_schema_sql(sql) == (SchemaObject(kind="type", name="my_status"),)


def test_parses_create_function_with_or_replace():
    sql = "CREATE OR REPLACE FUNCTION my_fetch_v1(queue_name varchar)\nRETURNS void AS $$ SELECT 1; $$ LANGUAGE sql;"
    assert SchemaObject(kind="function", name="my_fetch_v1") in parse_schema_sql(sql)


def test_parses_indexes_including_unique():
    sql = (
        "CREATE UNIQUE INDEX my_lock_idx ON my_jobs (lock);\n"
        "CREATE INDEX my_queue_idx ON my_jobs (queue_name);"
    )
    objs = parse_schema_sql(sql)
    assert SchemaObject(kind="index", name="my_lock_idx") in objs
    assert SchemaObject(kind="index", name="my_queue_idx") in objs


def test_parses_trigger_and_sequence():
    sql = (
        "CREATE SEQUENCE my_counter_seq;\n"
        "CREATE TRIGGER my_notify AFTER INSERT ON my_jobs\n"
        "    FOR EACH ROW EXECUTE PROCEDURE my_notify_fn();"
    )
    objs = parse_schema_sql(sql)
    assert SchemaObject(kind="sequence", name="my_counter_seq") in objs
    assert SchemaObject(kind="trigger", name="my_notify") in objs


def test_serial_column_yields_the_implicit_sequence():
    """bigserial/serial columns create a `<table>_<column>_seq` sequence
    behind the scenes, a schema tool enumerating sequences would propose
    dropping it, so the parser must surface it."""
    sql = "CREATE TABLE my_jobs (\n    id bigserial PRIMARY KEY,\n    n integer\n);"
    objs = parse_schema_sql(sql)
    assert SchemaObject(kind="sequence", name="my_jobs_id_seq") in objs


def test_identity_column_yields_the_implicit_sequence():
    sql = (
        "CREATE TABLE my_workers(\n"
        "    id bigint PRIMARY KEY GENERATED ALWAYS AS IDENTITY,\n"
        "    beat timestamp with time zone NOT NULL\n"
        ");"
    )
    objs = parse_schema_sql(sql)
    assert SchemaObject(kind="sequence", name="my_workers_id_seq") in objs


def test_statement_order_is_preserved():
    sql = (
        "CREATE TYPE t_status AS ENUM ('a');\n"
        "CREATE TABLE t_jobs (\n    id bigserial\n);\n"
        "CREATE FUNCTION t_fn() RETURNS void AS $$ SELECT 1; $$ LANGUAGE sql;"
    )
    names = [o.name for o in parse_schema_sql(sql)]
    assert names == ["t_status", "t_jobs", "t_jobs_id_seq", "t_fn"]


def test_comments_are_not_parsed():
    sql = (
        "-- CREATE TABLE commented_out (id integer);\n"
        "/* CREATE INDEX block_commented ON x (y);\n"
        "   spanning lines */\n"
        "    -- note: CREATE EXTENSION may fail on managed services\n"
        "CREATE TABLE real_one (\n    id integer\n);"
    )
    objs = parse_schema_sql(sql)
    assert [o.name for o in objs] == ["real_one"]


def test_create_inside_a_do_block_is_not_silently_skipped():
    """A guarded CREATE TABLE inside DO $$ ... $$ still creates the table.
    Skipping it because of indentation is the exact under-report this
    parser exists to make impossible."""
    sql = (
        "DO $$\n"
        "BEGIN\n"
        "    CREATE TABLE guarded_tbl (\n        id integer\n    );\n"
        "EXCEPTION WHEN duplicate_table THEN NULL;\n"
        "END $$;\n"
    )
    assert SchemaObject(kind="table", name="guarded_tbl") in parse_schema_sql(sql)


def test_two_create_statements_on_one_line_are_both_parsed():
    sql = "CREATE SEQUENCE first_seq; CREATE SEQUENCE second_seq;"
    names = [o.name for o in parse_schema_sql(sql)]
    assert names == ["first_seq", "second_seq"]


def test_create_extension_is_classified():
    sql = "DO $$\nBEGIN\n    CREATE EXTENSION IF NOT EXISTS plpgsql WITH SCHEMA pg_catalog;\nEND $$;"
    assert parse_schema_sql(sql) == (
        SchemaObject(kind="extension", name="plpgsql"),
    )


def test_unrecognized_create_statement_fails_loudly():
    """A DDL form the parser doesn't understand must raise, never be
    silently dropped, an incomplete list defeats the whole point of
    building an exclude list from it."""
    with pytest.raises(SchemaParseError, match="ROLE"):
        parse_schema_sql("CREATE ROLE queue_owner;")


def test_unrecognized_create_raises_even_when_indented_mid_line():
    with pytest.raises(SchemaParseError, match="PUBLICATION"):
        parse_schema_sql(
            "CREATE TABLE fine (\n    id integer\n);\n"
            "DO $$ BEGIN CREATE PUBLICATION sneaky; END $$;"
        )


def test_owned_schema_objects_helper_defaults_to_empty():
    class NoDeclaration:
        pass

    assert owned_schema_objects(NoDeclaration()) == ()


def test_owned_schema_objects_helper_calls_the_declaration():
    class Declares:
        def owned_schema_objects(self):
            return (SchemaObject(kind="table", name="acme_users"),)

    assert owned_schema_objects(Declares()) == (
        SchemaObject(kind="table", name="acme_users"),
    )
