"""Tests for `fymo schema provider-tables` (issue #51).

The command answers "which database objects do my configured providers
own" without touching any database, so schema diff tooling (pgschema and
friends) can build an exclude list instead of proposing DROP TABLE for
the live job queue.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from fymo.cli.commands.schema import run_provider_tables


def _write_project(tmp_path: Path, fymo_yml: str) -> Path:
    (tmp_path / "fymo.yml").write_text(fymo_yml)
    return tmp_path


@pytest.fixture
def procrastinate_project(tmp_path: Path) -> Path:
    return _write_project(
        tmp_path,
        "name: schema-test\njobs:\n  provider: procrastinate\n",
    )


def test_plain_output_is_one_kind_prefixed_object_per_line(procrastinate_project, capsys):
    run_provider_tables(procrastinate_project)
    out_lines = capsys.readouterr().out.strip().splitlines()
    assert "table procrastinate_jobs" in out_lines
    assert "table procrastinate_events" in out_lines
    assert "table procrastinate_periodic_defers" in out_lines
    assert "table procrastinate_workers" in out_lines
    assert "type procrastinate_job_status" in out_lines
    assert "sequence procrastinate_jobs_id_seq" in out_lines
    assert any(line.startswith("function procrastinate_") for line in out_lines)
    for line in out_lines:
        kind, _, name = line.partition(" ")
        assert kind in {"table", "type", "function", "sequence", "index", "trigger", "extension"}
        assert name and " " not in name


def test_json_output_carries_kind_name_and_provider(procrastinate_project, capsys):
    run_provider_tables(procrastinate_project, as_json=True)
    objects = json.loads(capsys.readouterr().out)
    assert isinstance(objects, list) and objects
    jobs_table = [o for o in objects if o["name"] == "procrastinate_jobs"]
    assert jobs_table == [
        {"kind": "table", "name": "procrastinate_jobs", "provider": "procrastinate"}
    ]
    assert all(set(o) == {"kind", "name", "provider"} for o in objects)


def test_no_owning_provider_prints_nothing_and_notes_it_on_stderr(tmp_path, capsys):
    """Default providers (threaded jobs, postgres broadcasts) own no
    schema objects: empty stdout, a stderr note, normal exit."""
    run_provider_tables(tmp_path)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no configured provider owns schema objects" in captured.err


def test_json_with_no_owning_provider_prints_an_empty_list(tmp_path, capsys):
    run_provider_tables(tmp_path, as_json=True)
    captured = capsys.readouterr()
    assert json.loads(captured.out) == []
    assert "no configured provider owns schema objects" in captured.err


def test_missing_procrastinate_package_fails_loudly(procrastinate_project, capsys, monkeypatch):
    """procrastinate configured but not installed: exit 1 naming the
    extra, never a silent partial list."""
    monkeypatch.setitem(sys.modules, "procrastinate", None)
    with pytest.raises(SystemExit) as exc_info:
        run_provider_tables(procrastinate_project)
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "fymo[procrastinate]" in captured.err


@pytest.fixture
def user_store_project(tmp_path: Path) -> Path:
    return _write_project(
        tmp_path,
        "name: schema-test\n"
        "auth:\n"
        "  user_store: fymo.auth.postgres_store.PostgresUserStore\n",
    )


def test_configured_postgres_user_store_objects_are_listed(user_store_project, capsys, monkeypatch):
    """The command's contract is no-database, no-env operation, so the
    identity tables must enumerate with DATABASE_URL unset even though
    constructing the store itself would refuse to boot without it."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    run_provider_tables(user_store_project)
    out_lines = capsys.readouterr().out.strip().splitlines()
    assert "table fymo_users" in out_lines
    assert "table fymo_user_oauth_identities" in out_lines
    assert "sequence fymo_users_id_seq" in out_lines
    assert "index fymo_users_email_lower_idx" in out_lines


def test_user_store_json_output_names_the_store(user_store_project, capsys, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    run_provider_tables(user_store_project, as_json=True)
    objects = json.loads(capsys.readouterr().out)
    users_table = [o for o in objects if o["name"] == "fymo_users"]
    assert users_table == [
        {"kind": "table", "name": "fymo_users", "provider": "PostgresUserStore"}
    ]


def test_default_user_store_contributes_nothing(tmp_path, capsys):
    """auth: configured but on the default SQLite store, whose objects
    live in its own auth.db file, not a shared Postgres schema."""
    _write_project(tmp_path, "name: schema-test\nauth:\n  enabled: true\n")
    run_provider_tables(tmp_path)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no configured provider owns schema objects" in captured.err


def test_jobs_and_user_store_enumerate_together(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    _write_project(
        tmp_path,
        "name: schema-test\n"
        "jobs:\n  provider: procrastinate\n"
        "auth:\n  user_store: fymo.auth.postgres_store.PostgresUserStore\n",
    )
    run_provider_tables(tmp_path)
    out_lines = capsys.readouterr().out.strip().splitlines()
    assert "table procrastinate_jobs" in out_lines
    assert "table fymo_users" in out_lines


def test_unimportable_user_store_fails_loudly(tmp_path, capsys):
    _write_project(
        tmp_path,
        "name: schema-test\nauth:\n  user_store: nope.not.There\n",
    )
    with pytest.raises(SystemExit) as exc_info:
        run_provider_tables(tmp_path)
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "nope.not.There" in captured.err


def test_schema_parse_error_uses_the_clean_error_path(procrastinate_project, capsys, monkeypatch):
    """A provider whose DDL the parser can't classify must exit 1 with a
    clean stderr message and empty stdout, not a raw traceback."""
    from fymo.core.schema import SchemaParseError
    from fymo.jobs.providers.procrastinate import ProcrastinateJobProvider

    def _boom(self):
        raise SchemaParseError("unrecognized CREATE statement: 'CREATE ROLE nope'")

    monkeypatch.setattr(ProcrastinateJobProvider, "owned_schema_objects", _boom)
    with pytest.raises(SystemExit) as exc_info:
        run_provider_tables(procrastinate_project)
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "unrecognized CREATE statement" in captured.err


def test_cli_end_to_end_against_a_scaffolded_project(procrastinate_project):
    """Acceptance (issue #51): the real CLI, run in a project configured
    with jobs: {provider: procrastinate}, enumerates every object a
    pgschema-style exclude list needs, with no database anywhere."""
    result = subprocess.run(
        ["fymo", "schema", "provider-tables"],
        cwd=procrastinate_project,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    lines = result.stdout.strip().splitlines()
    assert "table procrastinate_jobs" in lines
    assert "type procrastinate_job_status" in lines
    assert any(line.startswith("function procrastinate_") for line in lines)
