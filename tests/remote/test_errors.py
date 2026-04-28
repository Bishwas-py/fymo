import pytest
from fymo.remote.errors import RemoteError, NotFound, Unauthorized, Forbidden, Conflict


def test_remote_error_carries_status_and_code():
    err = RemoteError("oops", status=418, code="teapot")
    assert err.status == 418
    assert err.code == "teapot"
    assert str(err) == "oops"


def test_subclasses_have_correct_status():
    assert NotFound("x").status == 404
    assert NotFound("x").code == "not_found"
    assert Unauthorized("x").status == 401
    assert Unauthorized("x").code == "unauthorized"
    assert Forbidden("x").status == 403
    assert Forbidden("x").code == "forbidden"
    assert Conflict("x").status == 409
    assert Conflict("x").code == "conflict"


def test_subclass_message_preserved():
    e = NotFound("post 'foo' not found")
    assert "post 'foo' not found" in str(e)
