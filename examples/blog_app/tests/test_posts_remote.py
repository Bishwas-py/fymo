"""Tests for app/remote/posts.py (generated; they are yours).

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

from app.remote.posts import (
    create_post,
    delete_post,
    get_post,
    list_posts,
    update_post,
)


def test_list_posts_returns_the_seed_row():
    items = list_posts()
    assert any(item["created_by"] == "seed" for item in items)


def test_get_post_returns_the_seed_row():
    assert get_post(1)["created_by"] == "seed"


def test_get_post_unknown_id_raises_not_found():
    with pytest.raises(NotFound):
        get_post(999)


def test_create_post_attributes_the_signed_in_caller():
    with signed_in("u_test1") as ident:
        item = create_post(title="A new item")
    assert item["title"] == "A new item"
    assert item["created_by"] == ident.uid


def test_create_post_rejects_anonymous_callers():
    with request_scope(uid="u_anon", environ={}):
        with pytest.raises(RemoteError) as excinfo:
            create_post(title="nope")
    assert excinfo.value.status == 401


def test_update_post_by_the_owner():
    with signed_in("u_test1"):
        item = create_post(title="Draft")
        updated = update_post(item["id"], title="Final")
    assert updated["id"] == item["id"]
    assert updated["title"] == "Final"


def test_delete_post_by_the_owner():
    with signed_in("u_test1"):
        item = create_post(title="Disposable")
        deleted = delete_post(item["id"])
    assert deleted["id"] == item["id"]
    assert all(row["id"] != item["id"] for row in list_posts())


def test_someone_elses_post_reads_as_missing():
    # NotFound, never Forbidden: a distinguishable 403 would confirm the
    # id exists. The seed row's owner is "seed", so even a signed-in
    # caller cannot touch it.
    with signed_in("u_test1"):
        item = create_post(title="Mine")
        with pytest.raises(NotFound):
            update_post(1, title="steal the seed row")
        with acting_as("u_other"):
            with pytest.raises(NotFound):
                update_post(item["id"], title="steal")
            with pytest.raises(NotFound):
                delete_post(item["id"])


def test_mutations_reject_anonymous_callers():
    with request_scope(uid="u_anon", environ={}):
        with pytest.raises(RemoteError) as excinfo:
            update_post(1, title="nope")
        assert excinfo.value.status == 401
        with pytest.raises(RemoteError) as excinfo:
            delete_post(1)
        assert excinfo.value.status == 401
