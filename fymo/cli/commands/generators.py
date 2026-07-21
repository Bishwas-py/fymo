"""`fymo generate page/remote/resource`: the daily-loop generators.

Same ownership philosophy as `fymo generate auth`: templates are inert
text shipped inside the fymo package (fymo/cli/templates/page/ and
remote/), rendered once with the name's token variants, and the output
is plain app code fymo never imports at runtime. The only runtime
coupling is the existing auto-discovery (controllers by route,
app/remote/*.py by remote discovery, tests by pytest).

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

from fymo.cli.render import name_variants, render
from fymo.cli.writer import PlannedFile, execute_plan
from fymo.utils.colors import Color

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# auth owns app/auth/ and app/remote/auth.py; signin is the auto-public
# require_auth redirect target; root is the fymo.yml key for '/'; resources
# is the routes key the Router reads as its resource list, so injecting it
# as a page route would corrupt the routing table.
_RESERVED_NAMES = {"auth", "signin", "root", "resources"}

_APP_REMOTE_INIT = '"""Remote functions exposed to the browser."""\n'

_ROUTES_LINE_RE = re.compile(r"^routes:[ \t]*$", re.MULTILINE)


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


def _render_template(rel: str, tokens: dict) -> str:
    return render((_TEMPLATES_DIR / rel).read_text(), tokens)


# --------------- route injection ---------------


def _resource_names(routes: dict) -> set:
    names = set()
    for entry in routes.get("resources") or []:
        if isinstance(entry, str):
            names.add(entry)
        elif isinstance(entry, dict) and entry.get("name"):
            names.add(entry["name"])
    return names


def _plan_route_injection(root: Path, name: str) -> Tuple[Optional[PlannedFile], str, str]:
    """Decide how the route gets into fymo.yml.

    Returns (planned update or None, status, message) with status one of
    'inject', 'already', 'manual'. The manual message contains the exact
    line to add and where; it is the caller's job to print it and still
    exit 0 with the files generated.
    """
    route_line = f"  {name}: {name}.index"
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
        return None, "already", f"Route: /{name} is already declared in fymo.yml."
    if name in _resource_names(routes):
        return None, "already", (
            f"Route: /{name} is already routed by the `{name}` resources entry "
            "in fymo.yml."
        )

    # Scaffold shape: exactly one block-form `routes:` line to anchor on.
    if len(_ROUTES_LINE_RE.findall(text)) != 1:
        return None, "manual", manual
    match = _ROUTES_LINE_RE.search(text)
    insert_at = match.end()
    new_text = text[:insert_at] + f"\n{route_line}" + text[insert_at:]

    # A textual edit only counts if the parsed result is the old mapping
    # plus exactly the one new route.
    expected = copy.deepcopy(data)
    expected["routes"][name] = f"{name}.index"
    try:
        if yaml.safe_load(new_text) != expected:
            return None, "manual", manual
    except yaml.YAMLError:
        return None, "manual", manual

    entry = PlannedFile("fymo.yml", new_text, update=True)
    return entry, "inject", (
        f"Route: injected `{name}: {name}.index` into fymo.yml."
    )


# --------------- plans ---------------


def _page_plan(name: str, *, resource: bool = False) -> List[PlannedFile]:
    """resource=True swaps in the template wired to the generated remote
    (live list + require_auth create through $remote), so a resource page
    renders its resource instead of a placeholder."""
    tokens = name_variants(name)
    template = "resource_page/index.svelte.tmpl" if resource else "page/index.svelte.tmpl"
    plan = [
        PlannedFile(
            f"app/controllers/{name}.py",
            _render_template("page/controller.py.tmpl", tokens),
        ),
        PlannedFile(
            f"app/templates/{name}/index.svelte",
            _render_template(template, tokens),
        ),
    ]
    if resource:
        plan.append(PlannedFile(
            f"app/templates/{name}/Item.svelte",
            _render_template("resource_page/Item.svelte.tmpl", tokens),
        ))
    return plan


def _remote_plan(root: Path, name: str) -> List[PlannedFile]:
    tokens = name_variants(name)
    plan: List[PlannedFile] = []
    if not (root / "app" / "remote" / "__init__.py").exists():
        plan.append(PlannedFile("app/remote/__init__.py", _APP_REMOTE_INIT))
    plan.append(PlannedFile(
        f"app/remote/{name}.py",
        _render_template("remote/remote.py.tmpl", tokens),
    ))
    if not (root / "tests" / "conftest.py").exists():
        plan.append(PlannedFile(
            "tests/conftest.py",
            _render_template("remote/conftest.py.tmpl", tokens),
        ))
    plan.append(PlannedFile(
        f"tests/test_{name}_remote.py",
        _render_template("remote/test_remote.py.tmpl", tokens),
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

    plan: List[PlannedFile] = []
    if page:
        plan.extend(_page_plan(name, resource=page and remote))
    if remote:
        plan.extend(_remote_plan(root, name))

    route_status, route_message = "", ""
    if page:
        route_entry, route_status, route_message = _plan_route_injection(root, name)
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
