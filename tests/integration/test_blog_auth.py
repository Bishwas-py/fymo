"""Blog example: commenting is gated behind authentication."""
import sys
from pathlib import Path

import pytest

from fymo.remote.context import request_scope

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BLOG_DIR = REPO_ROOT / "examples" / "blog_app"


def _evict_app_modules():
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]


@pytest.fixture
def blog_on_path():
    if not BLOG_DIR.is_dir():
        pytest.skip("blog_app missing")
    # Other blog tests copy the app to a tmp dir and can leave a stale `app`
    # package cached (pointing at a since-deleted path). Evict before importing.
    _evict_app_modules()
    sys.path.insert(0, str(BLOG_DIR))
    yield
    sys.path.remove(str(BLOG_DIR))
    _evict_app_modules()


def test_create_comment_rejects_anonymous_users(blog_on_path):
    """An unauthenticated caller must be turned away by @require_auth before
    any comment is written — the gate fires ahead of the DB, so no store or
    seeded database is needed to prove it."""
    from app.remote.posts import create_comment, NewComment
    from fymo.auth.context import AuthRequired

    # request scope with no resolvable identity => current_uid() is None.
    with request_scope(uid="u_anon", environ={}):
        with pytest.raises(AuthRequired):
            create_comment("welcome-to-fymo", NewComment(body="hello"))
