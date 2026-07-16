"""Test setup for blog_app.

Auth and request-scope bootstrapping comes from fymo.testing (signed_in /
acting_as), so the only fixture the app owns is its own database: an
isolated SQLite file per test instead of app/data/blog.db.
"""
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def db(tmp_path, monkeypatch):
    from app.data import db as db_module

    test_db = db_module.DB(tmp_path / "blog.db")
    monkeypatch.setattr(db_module, "_db", test_db)
    return test_db
