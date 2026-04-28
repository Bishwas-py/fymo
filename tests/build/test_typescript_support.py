"""TypeScript inside <script lang='ts'> must compile and produce valid JS bundles."""
import json
from pathlib import Path
import pytest
from fymo.build.pipeline import BuildPipeline


@pytest.mark.usefixtures("node_available")
def test_typescript_script_tag_compiles(example_app: Path):
    # Inject a TS snippet into todos/test.svelte
    test_svelte = example_app / "app" / "templates" / "todos" / "test.svelte"
    original = test_svelte.read_text()
    patched = original.replace(
        "<script>",
        '<script lang="ts">\n  const greeting: string = "hello";',
        1,
    )
    test_svelte.write_text(patched)

    BuildPipeline(project_root=example_app).build(dev=False)

    # Build must succeed and emit a non-empty bundle
    manifest = json.loads((example_app / "dist" / "manifest.json").read_text())
    bundle = example_app / "dist" / manifest["routes"]["todos"]["client"]
    assert bundle.is_file()
    assert bundle.stat().st_size > 0
    # The TypeScript annotation should NOT appear in the output (it's stripped)
    assert ": string" not in bundle.read_text()
