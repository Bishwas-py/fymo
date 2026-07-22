"""`fymo destroy page/remote/resource`: generation is reversible.

The inverse of the generators, with the same safety brand. Destroy
computes the exact file set generate would produce today, deletes only
files byte-identical to a pristine render of the current templates
(either the full or the read-only variant), and refuses loudly, all or
nothing, when any target was modified since generation, unless --force.
Empty directories the generator created are removed; shared surface
never is: tests/conftest.py stays even when generation wrote it, and
app/remote/ only goes away when the generated module was the last one
and its __init__.py is still the pristine marker.

Route removal reverses injection with the same guard used to inject: a
textual edit counts only when the reparsed fymo.yml deep-equals the old
mapping minus exactly the one entry; anything else prints the exact
line to remove.
"""
import copy
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

from fymo.cli.commands import generators as gen
from fymo.utils.colors import Color

# Shared surface destroy never deletes, even when generation created it.
_NEVER_DELETE = {"tests/conftest.py", "app/remote/__init__.py"}


def _candidates(root: Path, name: str, *, page: bool, remote: bool) -> Dict[str, List[str]]:
    """relpath -> acceptable pristine contents (every variant that could
    have produced the file with the current templates)."""
    out: Dict[str, List[str]] = {}

    def add(plan):
        for pf in plan:
            if pf.relpath in _NEVER_DELETE:
                continue
            out.setdefault(pf.relpath, [])
            if pf.content not in out[pf.relpath]:
                out[pf.relpath].append(pf.content)

    if page and remote:
        for readonly in (False, True):
            add(gen._page_plan(root, name, resource=True, readonly=readonly))
    elif page:
        add(gen._page_plan(root, name, resource=False))
    if remote:
        for readonly in (False, True):
            add(gen._remote_plan(root, name, readonly=readonly))
    return out


# --------------- route removal ---------------


def _remove_line(text: str, index: int) -> str:
    lines = text.split("\n")
    del lines[index]
    return "\n".join(lines)


def _find_line(text: str, stripped: str) -> Optional[int]:
    for i, line in enumerate(text.split("\n")):
        if line.strip() == stripped:
            return i
    return None


def _plan_route_removal(root: Path, name: str, *, style: str) -> Tuple[Optional[str], str]:
    """Return (new fymo.yml text or None, message). None means no edit:
    either nothing to remove or the file needs a manual edit, and the
    message says which."""
    text = (root / "fymo.yml").read_text()
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return None, (
            "fymo.yml did not parse; remove the route for "
            f"/{name} manually if it is still declared."
        )
    if not isinstance(data, dict) or not isinstance(data.get("routes"), dict):
        return None, f"Route: no routes block in fymo.yml, nothing to remove for /{name}."
    routes = data["routes"]
    in_resources = name in gen._resource_names(routes)
    as_plain = name in routes

    if style == "resource" and in_resources:
        line = _find_line(text, f"- {name}")
        if line is None:
            return None, (
                f"Route: could not locate the `- {name}` resources entry "
                "textually; remove it from fymo.yml manually."
            )
        new_text = _remove_line(text, line)
        expected = copy.deepcopy(data)
        remaining = [e for e in routes["resources"] if e != name]
        if remaining:
            expected["routes"]["resources"] = remaining
        else:
            resources_line = _find_line(new_text, "resources:")
            if resources_line is None:
                return None, (
                    f"Route: remove the `- {name}` entry (and the now-empty "
                    "`resources:` key) from fymo.yml manually."
                )
            new_text = _remove_line(new_text, resources_line)
            del expected["routes"]["resources"]
        try:
            if yaml.safe_load(new_text) != expected:
                raise ValueError
        except (yaml.YAMLError, ValueError):
            return None, (
                "fymo.yml's routes block does not match the scaffold shape. "
                f"Remove this line under `resources:` yourself:\n\n    - {name}"
            )
        return new_text, f"Route: removed resources entry `- {name}` from fymo.yml."

    if as_plain:
        if routes[name] != f"{name}.index":
            return None, (
                f"Route: /{name} points at `{routes[name]}`, not the "
                "generated target; remove it from fymo.yml manually if that "
                "is intended."
            )
        manual = (
            "fymo.yml's routes block does not match the scaffold shape. "
            "Remove this line under `routes:` yourself:\n\n"
            f"  {name}: {name}.index"
        )
        line = _find_line(text, f"{name}: {name}.index")
        if line is None:
            return None, manual
        new_text = _remove_line(text, line)
        expected = copy.deepcopy(data)
        del expected["routes"][name]
        try:
            if yaml.safe_load(new_text) != expected:
                raise ValueError
        except (yaml.YAMLError, ValueError):
            return None, manual
        return new_text, f"Route: removed `{name}: {name}.index` from fymo.yml."

    if style != "resource" and in_resources:
        return None, (
            f"Route: /{name} is routed by a resources entry; "
            f"`fymo destroy resource {name}` removes that."
        )
    return None, f"Route: no route entry for /{name} in fymo.yml."


# --------------- directory cleanup ---------------


def _cleanup_dirs(root: Path, name: str, *, page: bool, remote: bool) -> List[str]:
    removed: List[str] = []
    if page:
        tdir = root / "app" / "templates" / name
        if tdir.is_dir() and not any(tdir.iterdir()):
            tdir.rmdir()
            removed.append(f"app/templates/{name}/")
    if remote:
        rdir = root / "app" / "remote"
        if rdir.is_dir():
            children = {p.name for p in rdir.iterdir()}
            pycache = rdir / "__pycache__"
            if children - {"__init__.py", "__pycache__"} == set():
                init = rdir / "__init__.py"
                # Only when the marker is still pristine: an edited
                # __init__.py is the app's code and stays.
                if not init.exists() or init.read_text() == gen._APP_REMOTE_INIT:
                    if pycache.is_dir():
                        shutil.rmtree(pycache)
                    if init.exists():
                        init.unlink()
                        removed.append("app/remote/__init__.py")
                    if not any(rdir.iterdir()):
                        rdir.rmdir()
                        removed.append("app/remote/")
    return removed


# --------------- entry point ---------------


def _run_destroy(
    command: str,
    name: str,
    *,
    page: bool,
    remote: bool,
    force: bool,
    dry_run: bool,
) -> None:
    root = gen._project_root(command)
    gen._validate_name(name, command)

    candidates = _candidates(root, name, page=page, remote=remote)
    deletable: List[str] = []
    modified: List[str] = []
    absent: List[str] = []
    for rel, contents in candidates.items():
        target = root / rel
        if not target.exists():
            absent.append(rel)
        elif target.read_text() in contents:
            deletable.append(rel)
        else:
            modified.append(rel)

    route_new_text: Optional[str] = None
    route_message = ""
    if page:
        style = "resource" if remote else "route"
        route_new_text, route_message = _plan_route_removal(root, name, style=style)

    if dry_run:
        for rel in deletable:
            print(f"  would delete  {rel}")
        for rel in modified:
            print(f"  would keep  {rel} (modified since generation; --force deletes)")
        for rel in absent:
            print(f"  absent  {rel} (nothing to delete)")
        if page:
            if route_new_text is not None:
                print(f"  would update  fymo.yml ({route_message})")
            else:
                print(route_message)
        return

    if modified and not force:
        for rel in modified:
            Color.print_error(
                f"{rel} was modified since generation and `{command}` only "
                "deletes byte-identical generated files. Rerun with --force "
                "to delete it anyway."
            )
        raise SystemExit(1)

    removed: List[str] = []
    for rel in deletable + (modified if force else []):
        (root / rel).unlink()
        removed.append(rel)
    removed.extend(_cleanup_dirs(root, name, page=page, remote=remote))
    if route_new_text is not None:
        (root / "fymo.yml").write_text(route_new_text)

    Color.print_success("Removed:")
    for rel in removed:
        print(f"  {rel}")
    for rel in absent:
        print(f"  {rel} was absent (nothing to delete)")
    if page:
        print(route_message)


def destroy_page(name: str, *, force: bool = False, dry_run: bool = False) -> None:
    _run_destroy("fymo destroy page", name, page=True, remote=False,
                 force=force, dry_run=dry_run)


def destroy_remote(name: str, *, force: bool = False, dry_run: bool = False) -> None:
    _run_destroy("fymo destroy remote", name, page=False, remote=True,
                 force=force, dry_run=dry_run)


def destroy_resource(name: str, *, force: bool = False, dry_run: bool = False) -> None:
    _run_destroy("fymo destroy resource", name, page=True, remote=True,
                 force=force, dry_run=dry_run)
