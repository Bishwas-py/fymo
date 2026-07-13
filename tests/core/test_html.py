from fymo.build.manifest import RouteAssets
from fymo.core.html import build_html


def test_minimal_html_structure():
    assets = RouteAssets(
        ssr="ssr/todos.mjs",
        client="client/todos.A1B2.js",
        css="client/todos.A1B2.css",
        preload=["client/chunk-datefns.X9Y8.js"],
    )
    html = build_html(
        body="<div class='todo-app'>hi</div>",
        head_extra="",
        props={"todos": []},
        assets=assets,
        title="Todos",
        asset_prefix="/dist",
    )
    assert "<!DOCTYPE html>" in html
    assert "<title>Todos</title>" in html
    assert '<link rel="stylesheet" href="/dist/client/todos.A1B2.css">' in html
    assert '<link rel="modulepreload" href="/dist/client/todos.A1B2.js">' in html
    assert '<link rel="modulepreload" href="/dist/client/chunk-datefns.X9Y8.js">' in html
    assert '<div id="svelte-app"><div class=\'todo-app\'>hi</div></div>' in html
    assert '<script type="application/json" id="svelte-props">{"todos": []}</script>' in html
    assert '<script type="module" src="/dist/client/todos.A1B2.js">' in html


def test_props_are_html_safe():
    assets = RouteAssets(ssr="x", client="x.js", css=None, preload=[])
    html = build_html(
        body="",
        head_extra="",
        props={"x": "</script><script>alert(1)//"},
        assets=assets,
        title="t",
        asset_prefix="/dist",
    )
    # The svelte-props block must not contain a literal `</script>` or `<script>`,
    # otherwise the embedded value would break out of the JSON island.
    start = html.index('id="svelte-props">') + len('id="svelte-props">')
    end = html.index('</script>', start)
    json_block = html[start:end]
    # < and > inside the JSON value must be escaped to \\u003c / \\u003e
    assert "<" not in json_block, f"unescaped < in JSON block: {json_block!r}"
    assert ">" not in json_block, f"unescaped > in JSON block: {json_block!r}"


def test_total_size_for_typical_page_under_5kb():
    assets = RouteAssets(
        ssr="ssr/todos.mjs",
        client="client/todos.A1B2.js",
        css="client/todos.A1B2.css",
        preload=[],
    )
    html = build_html(
        body="<div>" + ("a" * 1000) + "</div>",
        head_extra="<meta name='description' content='x'>",
        props={"a": 1},
        assets=assets,
        title="t",
        asset_prefix="/dist",
    )
    overhead = len(html) - 1000  # body content ~1KB
    assert overhead < 1500, f"HTML overhead {overhead}B is too large"


def test_remote_callable_serialized_as_marker(monkeypatch):
    """A callable from app.remote.* in props is serialized as {__fymo_remote: '<hash>/<fn>'}."""
    import sys, types
    fake_module = types.ModuleType("app.remote.posts")
    def create_post(title: str) -> str: return title
    create_post.__module__ = "app.remote.posts"
    fake_module.create_post = create_post
    sys.modules.setdefault("app", types.ModuleType("app"))
    sys.modules.setdefault("app.remote", types.ModuleType("app.remote"))
    sys.modules["app.remote.posts"] = fake_module

    # Stub out the manifest cache hash lookup
    from fymo.core import html as html_mod
    monkeypatch.setattr(html_mod, "_lookup_remote_hash", lambda mod_name: "abc123def456")

    from fymo.build.manifest import RouteAssets
    assets = RouteAssets(ssr="ssr/x.mjs", client="client/x.js", css=None, preload=[])
    out = html_mod.build_html(
        body="",
        head_extra="",
        props={"create_post": create_post},
        assets=assets,
        title="t",
        asset_prefix="/dist",
    )
    assert '"__fymo_remote":"abc123def456/create_post"' in out or '"__fymo_remote": "abc123def456/create_post"' in out

def test_disabled_soft_nav_meta_tag_emitted():
    """build_html injects fymo-disabled-resources meta when list non-empty."""
    assets = RouteAssets(ssr='x', client='x.js', css=None, preload=[])
    html = build_html(
        body='', head_extra='', props={}, assets=assets, title='t',
        disabled_soft_nav=['admin', 'api_keys'],
    )
    assert '<meta name="fymo-disabled-resources" content="admin,api_keys">' in html


def test_no_meta_when_disabled_list_empty():
    assets = RouteAssets(ssr='x', client='x.js', css=None, preload=[])
    html = build_html(body='', head_extra='', props={}, assets=assets, title='t')
    assert 'fymo-disabled-resources' not in html


def test_disabled_resource_names_html_escaped():
    assets = RouteAssets(ssr='x', client='x.js', css=None, preload=[])
    html = build_html(
        body='', head_extra='', props={}, assets=assets, title='t',
        disabled_soft_nav=['<script>alert(1)</script>'],
    )
    assert '<script>alert(1)' not in html  # escaped form is in there
    assert '&lt;script&gt;' in html

