"""Routes with :id capture should pass params as kwargs to getContext."""
from pathlib import Path
import pytest


@pytest.mark.usefixtures("node_available")
def test_param_passed_to_getContext(example_app, monkeypatch):
    # Create controller + template for the auto-generated 'todos/:id' show route
    show_ctrl = example_app / "app" / "controllers" / "todos.py"
    show_ctrl.write_text(
        "def getContext(id: str = ''):\n"
        "    return {'todo_id': id, 'name': f'todo-{id}'}\n"
    )

    show_tpl_dir = example_app / "app" / "templates" / "todos"
    show_tpl_dir.mkdir(parents=True, exist_ok=True)
    show_tpl = show_tpl_dir / "show.svelte"
    show_tpl.write_text(
        '<script>let { todo_id, name } = $props();</script>\n'
        '<div data-id={todo_id}>{name}</div>\n'
    )

    from fymo.build.pipeline import BuildPipeline
    BuildPipeline(project_root=example_app).build(dev=False)

    from fymo import create_app
    app = create_app(example_app)
    try:
        import io, sys
        responses = []
        def sr(s, h): responses.append((s, h))
        body = b"".join(app({
            "REQUEST_METHOD": "GET", "PATH_INFO": "/todos/abc123", "QUERY_STRING": "",
            "SERVER_NAME": "x", "SERVER_PORT": "0", "SERVER_PROTOCOL": "HTTP/1.1",
            "wsgi.input": io.BytesIO(), "wsgi.errors": sys.stderr, "wsgi.url_scheme": "http",
        }, sr))
        assert responses[0][0].startswith("200")
        assert b"todo-abc123" in body or b'data-id="abc123"' in body
    finally:
        if app.sidecar:
            app.sidecar.stop()
