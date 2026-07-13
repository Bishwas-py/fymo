"""Generate the SSR-side composed layout entry for routes with a layout chain."""
import os
from pathlib import Path
from typing import Optional

from fymo.build.discovery import Route


SSR_TREE_TEMPLATE = """\
<script>
{imports}
  let {{ leafProps, layoutProps }} = $props();

  // Bound via $state (never actually reassigned during SSR) purely so the
  // compiler treats this component reference as *dynamic* -- see the long
  // comment below on SSR_RESOURCE_BLOCK_WITH_LAYOUT for why a plain static
  // import reference here would structurally desync from the client shell's
  // hydration expectations.
  let CurrentLeaf = $state(Leaf);
{resource_state_decl}
  function onLeafError(error) {{
    if (typeof console !== 'undefined') {{
      console.error('[fymo] leaf render error:', error && error.stack || error && error.message || error);
    }}
  }}
</script>

{{#snippet leafSlot()}}
  <svelte:boundary onerror={{onLeafError}}>
    <CurrentLeaf {{...leafProps}} />
    {{#snippet failed(error, reset)}}
      <div class="fymo-leaf-error">Something went wrong. <button onclick={{reset}}>Retry</button></div>
    {{/snippet}}
  </svelte:boundary>
{{/snippet}}

{root_open}{resource_block}{root_close}"""

SSR_ROOT_OPEN = "<RootLayout {...layoutProps.root}>\n"
SSR_ROOT_CLOSE = "\n</RootLayout>"

# Structural mirror of entry_generator.py's SHELL_RESOURCE_BLOCK: the client
# shell ALWAYS wraps the leaf slot in an {#if}/{:else}/{/if} around the
# resource-layout slot (so soft-nav can swap one in without changing the
# shell's post-hydration markup shape). SSR has no such runtime concern --
# whether this route has a resource layout is a static, per-route fact known
# at generation time -- but it must still emit the SAME {#if}/{:else}/{/if}
# control-flow shape so the compiler's hydration anchor comments match the
# client shell's for the same route. The condition is a literal `true`/
# `false` rather than a reactive variable; Svelte does not dead-code-eliminate
# literal-condition {#if} blocks (verified against the compiler directly --
# both branches still compile and both `generate: 'server'` and
# `generate: 'client'` output the same anchor/comment structure regardless of
# the literal value), so this preserves hydration compatibility.
#
# CurrentResourceLayout is likewise bound via $state rather than referencing
# `ResourceLayout` (the static import) directly as the tag. This is not
# cosmetic: Svelte's compiler decides whether a `<Component .../>` tag emits
# the plain static-component codegen or the dynamic-component codegen (a
# `$.component(...)` wrapper with its own hydration marker comment) based on
# whether the tag's binding is "dynamic" -- and a binding is only dynamic if
# its `kind` is something other than `'normal'` (see
# `phases/2-analyze/visitors/Component.js`: `node.metadata.dynamic = ...
# binding.kind !== 'normal' ...`). A plain `import X from '...'` and even a
# plain `let x = X` both get `kind: 'normal'` -- only rune-derived bindings
# ($state, $props, $derived, ...) get a non-'normal' kind. The client shell's
# `CurrentResourceLayout`/`CurrentLeaf` are `$state(...)`, so they always
# compile to the dynamic-component form; a route's SSR tree MUST use the same
# form for the identical tag, or the server output is missing the hydration
# marker comment the client's compiled `$.component()` call requires --
# producing a real, user-visible bug: `svelte.dev/e/hydration_mismatch` plus
# the leaf's `<svelte:boundary>` catching a bare `HYDRATION_ERROR` sentinel
# and discarding the entire SSR'd subtree in favour of the `failed` snippet.
# (Root-caused by tracing a live `hydration_mismatch` through
# `read_hydration_instruction` straight to the `$.component()` call compiled
# for `<CurrentLeaf .../>` in the shell bundle -- confirmed by reproducing
# with and without this fix against a real browser.)
SSR_RESOURCE_BLOCK_WITH_LAYOUT = """{#if true}
  <CurrentResourceLayout {...layoutProps.resource}>
    {@render leafSlot()}
  </CurrentResourceLayout>
{:else}
  {@render leafSlot()}
{/if}
"""

# No resource layout for this route at build time -- both branches render the
# leaf directly and no <ResourceLayout> import/reference appears anywhere in
# the file. The {#if}/{:else}/{/if} wrapper is still emitted (with a literal
# `false` condition) purely for structural parity with the client shell,
# which always emits this wrapper for any route with a layout chain.
SSR_RESOURCE_BLOCK_WITHOUT_LAYOUT = """{#if false}
  {@render leafSlot()}
{:else}
  {@render leafSlot()}
{/if}
"""


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

    has_root = any(ref.level == "root" for ref in route.layout_chain)
    has_resource = any(ref.level == "resource" for ref in route.layout_chain)

    imports = ["  " + _import_line("Leaf", route.entry_path, out_dir_resolved)]
    for ref in route.layout_chain:
        name = "RootLayout" if ref.level == "root" else "ResourceLayout"
        imports.append("  " + _import_line(name, ref.svelte_path, out_dir_resolved))

    root_open = SSR_ROOT_OPEN if has_root else ""
    root_close = SSR_ROOT_CLOSE if has_root else ""
    resource_block = (
        SSR_RESOURCE_BLOCK_WITH_LAYOUT if has_resource else SSR_RESOURCE_BLOCK_WITHOUT_LAYOUT
    )
    # Same $state-binding rationale as CurrentLeaf above -- only emitted when
    # this route actually has a resource layout (ResourceLayout is only
    # imported in that case).
    resource_state_decl = (
        "  let CurrentResourceLayout = $state(ResourceLayout);\n" if has_resource else ""
    )

    body = SSR_TREE_TEMPLATE.format(
        imports="\n".join(imports),
        root_open=root_open,
        root_close=root_close,
        resource_block=resource_block,
        resource_state_decl=resource_state_decl,
    )

    out_path = out_dir / f"{route.name}.tree.svelte"
    out_path.write_text(body)
    return out_path
