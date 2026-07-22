"""Tests for app/remote/comments.py (generated; they are yours).

fymo.testing simulates identities without a server: signed_in() registers
an identity resolver and opens a request scope, which is exactly what
@require_auth checks; acting_as() switches to a second user mid-test to
prove one identity cannot touch another's rows. Anonymous callers need
only a plain request scope. Direct calls, no HTTP.
"""
import pytest

from fymo.remote import NotFound
from fymo.remote.context import request_scope
from fymo.remote.errors import RemoteError
from fymo.testing import acting_as, signed_in

from app.remote.comments import (
    create_comment,
    delete_comment,
    get_comment,
    list_comments,
    update_comment,
)


def test_list_comments_returns_the_seed_row():
    items = list_comments()
    assert any(item["created_by"] == "seed" for item in items)


def test_get_comment_returns_the_seed_row():
    assert get_comment(1)["created_by"] == "seed"


def test_get_comment_unknown_id_raises_not_found():
    with pytest.raises(NotFound):
        get_comment(999)


def test_create_comment_attributes_the_signed_in_caller():
    with signed_in("u_test1") as ident:
        item = create_comment(title="A new item")
    assert item["title"] == "A new item"
    assert item["created_by"] == ident.uid


def test_create_comment_rejects_anonymous_callers():
    with request_scope(uid="u_anon", environ={}):
        with pytest.raises(RemoteError) as excinfo:
            create_comment(title="nope")
    assert excinfo.value.status == 401


def test_update_comment_by_the_owner():
    with signed_in("u_test1"):
        item = create_comment(title="Draft")
        updated = update_comment(item["id"], title="Final")
    assert updated["id"] == item["id"]
    assert updated["title"] == "Final"


def test_delete_comment_by_the_owner():
    with signed_in("u_test1"):
        item = create_comment(title="Disposable")
        deleted = delete_comment(item["id"])
    assert deleted["id"] == item["id"]
    assert all(row["id"] != item["id"] for row in list_comments())


def test_someone_elses_comment_reads_as_missing():
    # NotFound, never Forbidden: a distinguishable 403 would confirm the
    # id exists. The seed row's owner is "seed", so even a signed-in
    # caller cannot touch it.
    with signed_in("u_test1"):
        item = create_comment(title="Mine")
        with pytest.raises(NotFound):
            update_comment(1, title="steal the seed row")
        with acting_as("u_other"):
            with pytest.raises(NotFound):
                update_comment(item["id"], title="steal")
            with pytest.raises(NotFound):
                delete_comment(item["id"])


def test_mutations_reject_anonymous_callers():
    with request_scope(uid="u_anon", environ={}):
        with pytest.raises(RemoteError) as excinfo:
            update_comment(1, title="nope")
        assert excinfo.value.status == 401
        with pytest.raises(RemoteError) as excinfo:
            delete_comment(1)
        assert excinfo.value.status == 401
