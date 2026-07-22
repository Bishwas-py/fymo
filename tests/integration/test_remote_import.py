"""<script> can import from $remote/<module> and esbuild resolves it."""
from pathlib import Path
import pytest
from fymo.build.pipeline import BuildPipeline


@pytest.mark.usefixtures("node_available")
def test_remote_import_resolves(example_app: Path):
    # Add a remote module
    remote = example_app / "app" / "remote"
    remote.mkdir(parents=True, exist_ok=True)
    (remote / "__init__.py").write_text("")
    (remote / "greeter.py").write_text(
        "from fymo.remote import remote\n"
        "@remote\n"
        "def hello(name: str) -> str:\n    return f'hi {name}'\n"
    )

    # Patch the co-located Item.svelte (imported by todos/index.svelte,
    # so it really lands in the compiled bundle) to import from $remote.
    test_svelte = example_app / "app" / "templates" / "todos" / "Item.svelte"
    new_content = (
        '<script>\n'
        '  import { hello } from "$remote/greeter";\n'
        '  let { item } = $props();\n'
        '  async function go() { await hello("world"); }\n'
        '</script>\n'
        '<li>{item.title}</li>\n'
    )
    test_svelte.write_text(new_content)

    BuildPipeline(project_root=example_app).build(dev=False)

    # The client bundle should reference the resolved remote path
    import json
    manifest = json.loads((example_app / "dist" / "manifest.json").read_text())
    bundle_path = example_app / "dist" / manifest["routes"]["todos"]["client"]
    bundle_text = bundle_path.read_text()
    # The $remote/greeter import was resolved: the new RPC route prefix and
    # the function name must appear in the bundle output.
    assert "/_fymo/remote/" in bundle_text
    assert "'hello'" in bundle_text or '"hello"' in bundle_text
