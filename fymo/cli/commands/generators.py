"""`fymo generate`: the daily-loop generators.

Same ownership philosophy as `fymo generate auth`: templates are inert
text shipped inside the fymo package (fymo/cli/templates/), rendered
once with the name's token variants, and the output is plain app code
fymo never imports at runtime. The only runtime coupling is the
existing auto-discovery (controllers by route, app/remote/*.py by
remote discovery, app/broadcasts/*.py by broadcast discovery, tests by
pytest).

Templates are overridable per project: a file at
<project>/.fymo/templates/<same relative path> wins over the packaged
one, with identical tokens and conflict behavior (see
fymo.cli.render.load_template). `fymo generate templates` publishes the
packaged tree there for editing.

Route wiring is the one in-place edit. In scaffolded projects the
router reads fymo.yml (it wins over config/routes.py in
FymoApp._initialize_router), so injection targets fymo.yml's routes
block, and only when the file still matches the shape fymo's own
scaffold produces: a top-level `routes:` mapping written in block form.
The injected file is re-parsed and must equal the old mapping plus
exactly the one new route, or nothing is written and the exact line to
add is printed instead. Never a half-write, never a silent skip.
"""
import copy
import keyword
import re
from pathlib import Path
from typing import List, Optional, Tuple

import yaml

from fymo.cli.render import PACKAGED_TEMPLATES_DIR, load_template, name_variants, render
from fymo.cli.writer import PlannedFile, execute_plan
from fymo.utils.colors import Color

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# auth owns app/auth/ and app/remote/auth.py; signin is the auto-public
# require_auth redirect target; root is the fymo.yml key for '/'; resources
# is the routes key the Router reads as its resource list, so injecting it
# as a page route would corrupt the routing table.
_RESERVED_NAMES = {"auth", "signin", "root", "resources"}

_APP_REMOTE_INIT = '"""Remote functions exposed to the browser."""\n'
_APP_BROADCASTS_INIT = '"""Broadcast channels: every top-level function is a channel."""\n'

# Components are imported as classes ($components/StatCard.svelte), so
# their names follow Svelte's component convention, not the route rule.
_COMPONENT_NAME_RE = re.compile(r"^[A-Z][A-Za-z0-9]*$")

_ROUTES_LINE_RE = re.compile(r"^routes:[ \t]*$", re.MULTILINE)
_RESOURCES_LINE_RE = re.compile(r"^  resources:[ \t]*$", re.MULTILINE)


def _refuse(message: str) -> None:
    Color.print_error(message)
    raise SystemExit(1)


def _project_root(command: str) -> Path:
    root = Path.cwd()
    if not (root / "fymo.yml").is_file():
        _refuse(
            f"No fymo.yml here. Run `{command}` from the project root "
            "(the directory containing fymo.yml)."
        )
    return root


def _validate_name(name: str, command: str) -> None:
    if not _NAME_RE.match(name):
        _refuse(
            f"Invalid name '{name}' for `{command}`: use a lowercase Python "
            "identifier (letters, digits, underscores; starts with a letter), "
            "no path separators."
        )
    if keyword.iskeyword(name):
        _refuse(f"Invalid name '{name}' for `{command}`: it is a Python keyword.")
    if name in _RESERVED_NAMES:
        _refuse(
            f"Invalid name '{name}' for `{command}`: it is reserved "
            f"({', '.join(sorted(_RESERVED_NAMES))})."
        )


def _render_template(root: Path, rel: str, tokens: dict) -> str:
    return render(load_template(root, rel), tokens)


# --------------- route injection ---------------


def _resource_names(routes: dict) -> set:
    names = set()
    for entry in routes.get("resources") or []:
        if isinstance(entry, str):
            names.add(entry)
        elif isinstance(entry, dict) and entry.get("name"):
            names.add(entry["name"])
    return names


def _verified_update(new_text: str, expected: dict) -> Optional[PlannedFile]:
    """A textual edit only counts if the parsed result equals `expected`
    (the old mapping plus exactly the intended addition)."""
    try:
        if yaml.safe_load(new_text) != expected:
            return None
    except yaml.YAMLError:
        return None
    return PlannedFile("fymo.yml", new_text, update=True)


def _list_item_indent(text: str, after: int) -> str:
    """Indent of the first list item following position `after`, for
    matching an existing resources list's style; the scaffold's four
    spaces otherwise. The parse verification is the real guard."""
    for line in text[after:].split("\n")[1:]:
        if not line.strip():
            continue
        item = re.match(r"^(\s+)-\s", line)
        return item.group(1) if item else "    "
    return "    "


def _plan_route_injection(
    root: Path, name: str, *, style: str = "route"
) -> Tuple[Optional[PlannedFile], str, str]:
    """Decide how the route gets into fymo.yml.

    Returns (planned update or None, status, message) with status one of
    'inject', 'already', 'manual'. The manual message contains the exact
    lines to add and where; it is the caller's job to print it and still
    exit 0 with the files generated.

    style="route" injects a plain `<name>: <name>.index` entry (one URL,
    what `generate page` needs). style="resource" injects into the
    resources list instead, because /name/<id> and the other detail URLs
    only exist through the Router's resources expansion; a plain route
    would leave every generated show page unreachable.
    """
    resource = style == "resource"
    route_line = f"  {name}: {name}.index"
    if resource:
        manual = (
            "fymo.yml's routes block does not match the shape the fymo "
            "scaffold produces, so the route was not injected. Add these "
            "lines under `routes:` in fymo.yml (or add just the item to an "
            "existing `resources:` list):\n\n"
            f"  resources:\n    - {name}\n"
        )
    else:
        manual = (
            "fymo.yml's routes block does not match the shape the fymo scaffold "
            "produces, so the route was not injected. Add this line under "
            "`routes:` in fymo.yml:\n\n"
            f"{route_line}\n"
        )
    text = (root / "fymo.yml").read_text()
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return None, "manual", manual
    if not isinstance(data, dict) or not isinstance(data.get("routes"), dict):
        return None, "manual", manual
    routes = data["routes"]

    if name in routes or f"/{name}" in routes:
        if resource:
            return None, "already", (
                f"Route: /{name} is already declared as a plain route in "
                f"fymo.yml. Detail routes (/{name}/<id>) come from a "
                "resources entry; replace the plain route with:\n\n"
                f"  resources:\n    - {name}"
            )
        return None, "already", f"Route: /{name} is already declared in fymo.yml."
    if name in _resource_names(routes):
        return None, "already", (
            f"Route: /{name} is already routed by the `{name}` resources entry "
            "in fymo.yml."
        )

    expected = copy.deepcopy(data)
    if resource:
        matches = _RESOURCES_LINE_RE.findall(text)
        existing = routes.get("resources")
        if len(matches) == 1 and (existing is None or isinstance(existing, list)):
            # Prepend to the block-form resources list (empty is fine).
            anchor = _RESOURCES_LINE_RE.search(text)
            indent = _list_item_indent(text, anchor.end())
            new_text = text[:anchor.end()] + f"\n{indent}- {name}" + text[anchor.end():]
            expected["routes"]["resources"] = [name] + (existing or [])
        elif not matches and "resources" not in routes and len(_ROUTES_LINE_RE.findall(text)) == 1:
            # No resources list yet: start one under routes:.
            anchor = _ROUTES_LINE_RE.search(text)
            new_text = text[:anchor.end()] + f"\n  resources:\n    - {name}" + text[anchor.end():]
            expected["routes"]["resources"] = [name]
        else:
            return None, "manual", manual
        entry = _verified_update(new_text, expected)
        if entry is None:
            return None, "manual", manual
        return entry, "inject", (
            f"Route: injected resources entry `- {name}` into fymo.yml "
            f"(routes /{name} and /{name}/<id>)."
        )

    # Scaffold shape: exactly one block-form `routes:` line to anchor on.
    if len(_ROUTES_LINE_RE.findall(text)) != 1:
        return None, "manual", manual
    anchor = _ROUTES_LINE_RE.search(text)
    new_text = text[:anchor.end()] + f"\n{route_line}" + text[anchor.end():]
    expected["routes"][name] = f"{name}.index"
    entry = _verified_update(new_text, expected)
    if entry is None:
        return None, "manual", manual
    return entry, "inject", (
        f"Route: injected `{name}: {name}.index` into fymo.yml."
    )


# --------------- plans ---------------


def _page_plan(root: Path, name: str, *, resource: bool = False, readonly: bool = False) -> List[PlannedFile]:
    """resource=True swaps in the templates wired to the generated remote:
    a live list + require_auth create through $remote, a co-located
    show.svelte detail view reached via /name/<id> (rendered through
    index.svelte, the directory's one built entry), and a controller that
    threads the route's id param down as item_id. readonly=True (the
    no-auth-project variant) renders the same file set without the create
    form or owner controls."""
    tokens = name_variants(name)
    controller = "resource_page/controller.py.tmpl" if resource else "page/controller.py.tmpl"
    if resource:
        index = ("resource_page/index_readonly.svelte.tmpl" if readonly
                 else "resource_page/index.svelte.tmpl")
        show = ("resource_page/show_readonly.svelte.tmpl" if readonly
                else "resource_page/show.svelte.tmpl")
    else:
        index = "page/index.svelte.tmpl"
    plan = [
        PlannedFile(
            f"app/controllers/{name}.py",
            _render_template(root, controller, tokens),
        ),
        PlannedFile(
            f"app/templates/{name}/index.svelte",
            _render_template(root, index, tokens),
        ),
    ]
    if resource:
        plan.append(PlannedFile(
            f"app/templates/{name}/show.svelte",
            _render_template(root, show, tokens),
        ))
        plan.append(PlannedFile(
            f"app/templates/{name}/Item.svelte",
            _render_template(root, "resource_page/Item.svelte.tmpl", tokens),
        ))
    return plan


def _remote_plan(root: Path, name: str, *, readonly: bool = False) -> List[PlannedFile]:
    tokens = name_variants(name)
    remote_tmpl = "remote/remote_readonly.py.tmpl" if readonly else "remote/remote.py.tmpl"
    test_tmpl = ("remote/test_remote_readonly.py.tmpl" if readonly
                 else "remote/test_remote.py.tmpl")
    plan: List[PlannedFile] = []
    if not (root / "app" / "remote" / "__init__.py").exists():
        plan.append(PlannedFile("app/remote/__init__.py", _APP_REMOTE_INIT))
    plan.append(PlannedFile(
        f"app/remote/{name}.py",
        _render_template(root, remote_tmpl, tokens),
    ))
    if not (root / "tests" / "conftest.py").exists():
        plan.append(PlannedFile(
            "tests/conftest.py",
            _render_template(root, "remote/conftest.py.tmpl", tokens),
        ))
    plan.append(PlannedFile(
        f"tests/test_{name}_remote.py",
        _render_template(root, test_tmpl, tokens),
    ))
    return plan


# --------------- entry points ---------------


def _run(
    command: str,
    name: str,
    *,
    page: bool,
    remote: bool,
    force: bool,
    dry_run: bool,
    diff: bool,
) -> None:
    root = _project_root(command)
    _validate_name(name, command)

    # No app/auth/ means no identity resolver: every @require_auth
    # mutation would answer 401 for everyone, so remote generation falls
    # back to the read-only variant (list + get) until auth exists.
    readonly = remote and not (root / "app" / "auth").is_dir()

    plan: List[PlannedFile] = []
    if page:
        plan.extend(_page_plan(root, name, resource=page and remote, readonly=readonly))
    if remote:
        plan.extend(_remote_plan(root, name, readonly=readonly))

    route_status, route_message = "", ""
    if page:
        style = "resource" if remote else "route"
        route_entry, route_status, route_message = _plan_route_injection(
            root, name, style=style
        )
        if route_entry is not None:
            plan.append(route_entry)

    written = execute_plan(
        root, plan, command=command, force=force, dry_run=dry_run, diff=diff
    )
    if dry_run or diff:
        if page and route_status != "inject":
            print(route_message)
        return

    Color.print_success("Generated:")
    for rel in written:
        print(f"  {rel}")
    if page:
        if route_status == "manual":
            Color.print_warning(route_message)
        else:
            print(route_message)
    if remote:
        print(f"Run the generated test with: pytest tests/test_{name}_remote.py")
        if readonly:
            singular = name_variants(name)["name_singular"]
            Color.print_warning(
                f"No app/auth/ in this project, so {name} was generated "
                f"read-only (list_{name} and get_{singular} only). For full "
                f"CRUD: run `fymo generate auth`, then `{command} {name} "
                "--force`."
            )


def generate_page(
    name: str, *, force: bool = False, dry_run: bool = False, diff: bool = False
) -> None:
    _run("fymo generate page", name, page=True, remote=False,
         force=force, dry_run=dry_run, diff=diff)


def generate_remote(
    name: str, *, force: bool = False, dry_run: bool = False, diff: bool = False
) -> None:
    _run("fymo generate remote", name, page=False, remote=True,
         force=force, dry_run=dry_run, diff=diff)


def generate_resource(
    name: str, *, force: bool = False, dry_run: bool = False, diff: bool = False
) -> None:
    _run("fymo generate resource", name, page=True, remote=True,
         force=force, dry_run=dry_run, diff=diff)


def generate_component(
    name: str, *, force: bool = False, dry_run: bool = False, diff: bool = False
) -> None:
    command = "fymo generate component"
    root = _project_root(command)
    if not _COMPONENT_NAME_RE.match(name):
        _refuse(
            f"Invalid component name '{name}' for `{command}`: use PascalCase "
            "(letters and digits, starts with a capital), e.g. StatCard."
        )
    plan = [PlannedFile(
        f"app/components/{name}.svelte",
        _render_template(root, "component/Component.svelte.tmpl", {"component_name": name}),
    )]
    written = execute_plan(root, plan, command=command,
                           force=force, dry_run=dry_run, diff=diff)
    if dry_run or diff:
        return
    Color.print_success("Generated:")
    for rel in written:
        print(f"  {rel}")
    print(f"Import it with: import {name} from '$components/{name}.svelte';")


def generate_layout(
    section: str, *, force: bool = False, dry_run: bool = False, diff: bool = False
) -> None:
    command = "fymo generate layout"
    root = _project_root(command)
    _validate_name(section, command)
    if not (root / "app" / "templates" / section).is_dir():
        _refuse(
            f"app/templates/{section}/ does not exist yet, and a layout "
            "without pages is dead code. Generate a page first: "
            f"`fymo generate page {section}`."
        )
    plan = [PlannedFile(
        f"app/templates/{section}/_layout.svelte",
        _render_template(root, "layout/_layout.svelte.tmpl", name_variants(section)),
    )]
    written = execute_plan(root, plan, command=command,
                           force=force, dry_run=dry_run, diff=diff)
    if dry_run or diff:
        return
    Color.print_success("Generated:")
    for rel in written:
        print(f"  {rel}")
    print(f"Every page under app/templates/{section}/ now renders inside it.")


def generate_broadcast(
    name: str, *, force: bool = False, dry_run: bool = False, diff: bool = False
) -> None:
    command = "fymo generate broadcast"
    root = _project_root(command)
    _validate_name(name, command)
    tokens = name_variants(name)
    plan: List[PlannedFile] = []
    if not (root / "app" / "broadcasts" / "__init__.py").exists():
        plan.append(PlannedFile("app/broadcasts/__init__.py", _APP_BROADCASTS_INIT))
    plan.append(PlannedFile(
        f"app/broadcasts/{name}.py",
        _render_template(root, "broadcast/broadcast.py.tmpl", tokens),
    ))
    if not (root / "tests" / "conftest.py").exists():
        plan.append(PlannedFile(
            "tests/conftest.py",
            _render_template(root, "remote/conftest.py.tmpl", tokens),
        ))
    plan.append(PlannedFile(
        f"tests/test_{name}_broadcast.py",
        _render_template(root, "broadcast/test_broadcast.py.tmpl", tokens),
    ))
    written = execute_plan(root, plan, command=command,
                           force=force, dry_run=dry_run, diff=diff)
    if dry_run or diff:
        return
    Color.print_success("Generated:")
    for rel in written:
        print(f"  {rel}")
    print(f"Publish with fymo.broadcast.publish('{name}_activity', id=..., data=...);")
    print(f"subscribe in the browser via $broadcast/{name} after `fymo build`.")


def publish_templates(
    *, force: bool = False, dry_run: bool = False, diff: bool = False
) -> None:
    """Copy the packaged template tree into .fymo/templates/ for editing.

    Published files win over the packaged ones on every later generate
    run (see fymo.cli.render.load_template); deleting a published file
    falls back to the packaged template."""
    command = "fymo generate templates"
    root = _project_root(command)
    # project/ is the fymo new scaffold, rendered outside any project, so
    # overrides can never reach it; publishing it would be dead files.
    plan = [
        PlannedFile(
            f".fymo/templates/{tmpl.relative_to(PACKAGED_TEMPLATES_DIR).as_posix()}",
            tmpl.read_text(),
        )
        for tmpl in sorted(PACKAGED_TEMPLATES_DIR.rglob("*.tmpl"))
        if tmpl.relative_to(PACKAGED_TEMPLATES_DIR).parts[0] != "project"
    ]
    written = execute_plan(root, plan, command=command,
                           force=force, dry_run=dry_run, diff=diff)
    if dry_run or diff:
        return
    Color.print_success("Published:")
    for rel in written:
        print(f"  {rel}")
    print("Edit these; generators prefer them over the packaged templates.")
    print("Delete a file to fall back to the packaged version.")
