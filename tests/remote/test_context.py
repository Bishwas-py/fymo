"""request_scope is a contextvar-based scope; current_uid() resolves inside it."""
import pytest
from fymo.remote.context import request_scope, request_event
from fymo.remote.identity import current_uid


def test_current_uid_outside_scope_raises():
    with pytest.raises(RuntimeError, match="outside"):
        current_uid()


def test_current_uid_inside_scope():
    with request_scope(uid="u_test", environ={"REMOTE_ADDR": "127.0.0.1"}):
        assert current_uid() == "u_test"
        ev = request_event()
        assert ev.uid == "u_test"
        assert ev.remote_addr == "127.0.0.1"


def test_scope_is_cleaned_up_after_exit():
    with request_scope(uid="u_x", environ={}):
        assert current_uid() == "u_x"
    with pytest.raises(RuntimeError):
        current_uid()
