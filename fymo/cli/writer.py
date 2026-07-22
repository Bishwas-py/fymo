"""Plan writer shared by every generator. Stdlib only.

A generator builds a plan (ordered PlannedFile entries) and hands it
here; this module owns the conflict policy so every generator behaves
the same way:

- default: refuse loudly when any non-update target already exists,
  naming each file, writing nothing (all-or-nothing);
- force: overwrite;
- dry_run: print every path with a would-create / would-overwrite /
  would-update marker, write nothing;
- diff: print a unified diff for each differing existing file, write
  nothing.

`update` entries are targets expected to exist (route injection rewrites
fymo.yml in place); they never trigger the refusal and are labeled
"update" in previews.
"""
import difflib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from fymo.utils.colors import Color


@dataclass(frozen=True)
class PlannedFile:
    relpath: str
    content: str
    update: bool = False
    chmod: Optional[int] = None


def execute_plan(
    root: Path,
    plan: List[PlannedFile],
    *,
    command: str,
    force: bool = False,
    dry_run: bool = False,
    diff: bool = False,
) -> List[str]:
    """Execute `plan` against `root`; return the written relpaths.

    `command` is the user-facing command name for the refusal message
    (e.g. "fymo generate page"). dry_run and diff write nothing and
    return []. The default mode raises SystemExit(1) via a loud error
    when any non-update target exists.
    """
    if dry_run:
        for entry in plan:
            target = root / entry.relpath
            if entry.update:
                marker = "would update"
            elif target.exists():
                marker = "would overwrite"
            else:
                marker = "would create"
            print(f"  {marker}  {entry.relpath}")
        return []

    if diff:
        for entry in plan:
            target = root / entry.relpath
            if not target.exists():
                print(f"  would create  {entry.relpath} (new file)")
                continue
            current = target.read_text()
            if current == entry.content:
                continue
            lines = difflib.unified_diff(
                current.splitlines(keepends=True),
                entry.content.splitlines(keepends=True),
                fromfile=f"a/{entry.relpath}",
                tofile=f"b/{entry.relpath}",
            )
            print("".join(lines), end="")
        return []

    if not force:
        conflicts = [
            entry.relpath
            for entry in plan
            if not entry.update and (root / entry.relpath).exists()
        ]
        if conflicts:
            for rel in conflicts:
                Color.print_error(
                    f"{rel} already exists and `{command}` never overwrites it. "
                    "Delete or move it first, then rerun (or pass --force to "
                    "overwrite, --diff to preview)."
                )
            raise SystemExit(1)

    written: List[str] = []
    for entry in plan:
        target = root / entry.relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(entry.content)
        if entry.chmod is not None:
            os.chmod(target, entry.chmod)
        written.append(entry.relpath)
    return written
