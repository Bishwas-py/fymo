"""_evict_stale_app_cache: eviction must track the project ROOT, not fire
unconditionally on every call.

The bug: the eviction check compared app.__path__ (the "app" package's own
directory, e.g. "/proj/app") against sys.path (which holds project roots,
e.g. "/proj", never the "app" subdirectory itself). That comparison never
matched, so app.* was evicted and fully reimported on every single remote
dispatch, in both dev and prod, silently defeating anything keyed on the
resulting function objects' identity (like the router's signature/hints
cache) even when the project root never changed between requests.

These tests pin down the fixed invariant from both directions:
  1. within one continuously-running project root, no eviction fires
     across repeated dispatches, so function identity (and therefore any
     identity-keyed cache) stays stable.
  2. across a genuine project-root change (e.g. one pytest session running
     many tests, each building a fresh "app" package under its own
     tmp_path, exactly as tests/conftest.py's blog_app fixture and
     tests/remote/test_router.py's remote_project fixture do), eviction
     still correctly fires and the newly active root's code is what gets
     dispatched, not a stale cached function from the old root.
"""
import sys
import pytest
from fymo.remote import router as router_mod


def _scaffold(root, hello_body: str):
    (root / "app").mkdir()
    (root / "app" / "__init__.py").write_text("")
    (root / "app" / "remote").mkdir()
    (root / "app" / "remote" / "__init__.py").write_text("")
    (root / "app" / "remote" / "posts.py").write_text(hello_body)


@pytest.fixture(autouse=True)
def _clean_app_modules():
    """Belt-and-suspenders: no test in this file should leak an "app" module
    into any other test file, regardless of what sys.path manipulation it
    does mid-test."""
    yield
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]


def test_no_eviction_across_repeated_calls_within_one_stable_root(tmp_path):
    """Simulates one continuously-running FymoApp: project_root is inserted
    onto sys.path once (as FymoApp.__init__ does) and never touched again
    between requests. Two dispatches for the same function must return the
    exact same function object, proving no reimport (and thus no reflection
    re-work) happened in between."""
    _scaffold(tmp_path, "def hello(name: str) -> str: return f'hi {name}'\n")
    root_str = str(tmp_path)
    sys.path.insert(0, root_str)
    try:
        fn1, sig1, hints1 = router_mod._resolve_fn_in_module("posts", "hello")
        fn2, sig2, hints2 = router_mod._resolve_fn_in_module("posts", "hello")
        assert fn1 is not None
        assert fn1 is fn2, (
            "expected the same function object across two dispatches with an "
            "unchanged project root; got a fresh reimport instead"
        )
    finally:
        if root_str in sys.path:
            sys.path.remove(root_str)


def test_eviction_fires_when_project_root_changes(tmp_path_factory):
    """Simulates a pytest session (or a dev-mode project-root switch) moving
    from one "app" package to a different one under the same name, without
    any manual sys.modules cleanup in between (that's exactly the job
    _evict_stale_app_cache exists to do). The second dispatch must return
    project B's function and behavior, not a stale cached function still
    pointing at project A's file."""
    root_a = tmp_path_factory.mktemp("proj_a")
    root_b = tmp_path_factory.mktemp("proj_b")
    _scaffold(root_a, "def hello() -> str: return 'from-a'\n")
    _scaffold(root_b, "def hello() -> str: return 'from-b'\n")

    root_a_str, root_b_str = str(root_a), str(root_b)
    sys.path.insert(0, root_a_str)
    try:
        fn_a, _, _ = router_mod._resolve_fn_in_module("posts", "hello")
        assert fn_a is not None
        assert fn_a() == "from-a"
    finally:
        if root_a_str in sys.path:
            sys.path.remove(root_a_str)

    # Root A is gone from sys.path now; root B takes its place, same as a
    # fresh FymoApp constructed against a different project. Nothing here
    # manually clears sys.modules; that eviction must happen on its own.
    sys.path.insert(0, root_b_str)
    try:
        fn_b, _, _ = router_mod._resolve_fn_in_module("posts", "hello")
        assert fn_b is not None
        assert fn_b is not fn_a, "stale function object from project A was reused for project B"
        assert fn_b() == "from-b", "dispatch returned project A's stale behavior instead of project B's"
    finally:
        if root_b_str in sys.path:
            sys.path.remove(root_b_str)
