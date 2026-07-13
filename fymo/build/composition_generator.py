"""Generate the SSR-side composed layout entry for routes with a layout chain."""
import os
from pathlib import Path
from typing import Optional

from fymo.build.discovery import Route


SSR_TREE_TEMPLATE = """\
<script>
  let {{ leafProps, layoutProps }} = $props();
</script>
{open_tags}<Leaf {{...leafProps}} />
{close_tags}"""


def _import_line(name: str, path: Path, out_dir_resolved: Path) -> str:
    rel = os.path.relpath(path, out_dir_resolved)
    module_path = rel.replace(os.sep, "/")
    if not module_path.startswith("."):
        module_path = "./" + module_path
    return f"import {name} from '{module_path}';"


def generate_ssr_tree(route: Route, out_dir: Path) -> Optional[Path]:
    """Write out_dir/<route.name>.tree.svelte composing route.layout_chain
    around the leaf, for routes that have a layout chain. Returns the
    written path, or None when the chain is empty (caller falls back to
    route.entry_path, the raw leaf, unchanged -- zero overhead for routes
    that don't use layouts)."""
    if not route.layout_chain:
        return None

    if not route.entry_path.is_file():
        raise FileNotFoundError(
            f"route '{route.name}': leaf component {route.entry_path} does not exist "
            f"(deleted after discovery? re-run `fymo build`)"
        )
    for ref in route.layout_chain:
        if not ref.svelte_path.is_file():
            raise FileNotFoundError(
                f"route '{route.name}': {ref.level} layout {ref.svelte_path} does not exist "
                f"(deleted after discovery? re-run `fymo build`)"
            )

    out_dir.mkdir(parents=True, exist_ok=True)
    out_dir_resolved = out_dir.resolve()

    imports = [_import_line("Leaf", route.entry_path, out_dir_resolved)]
    open_tags = []
    close_tags = []
    for ref in route.layout_chain:
        component_name = "RootLayout" if ref.level == "root" else "ResourceLayout"
        imports.append(_import_line(component_name, ref.svelte_path, out_dir_resolved))
        props_key = "root" if ref.level == "root" else "resource"
        open_tags.append(f"<{component_name} {{...layoutProps.{props_key}}}>\n")
        close_tags.insert(0, f"</{component_name}>\n")

    body = SSR_TREE_TEMPLATE.format(
        open_tags="".join(open_tags),
        close_tags="".join(close_tags),
    )
    # Imports go above the props declaration inside the same <script> block.
    body = body.replace(
        "let {{ leafProps, layoutProps }} = $props();".replace("{{", "{").replace("}}", "}"),
        "\n  ".join(imports) + "\n\n  let { leafProps, layoutProps } = $props();",
    )

    out_path = out_dir / f"{route.name}.tree.svelte"
    out_path.write_text(body)
    return out_path
