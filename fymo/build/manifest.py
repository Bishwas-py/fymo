"""dist/manifest.json read/write contract between build and runtime."""
import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional


MANIFEST_VERSION = 2


@dataclass(frozen=True)
class LayoutRefAsset:
    """Runtime-facing counterpart of build/discovery.py's LayoutRef — no
    svelte_path (already compiled by the time the manifest is read)."""
    level: str                          # "root" | "resource"
    id: str
    controller_module: Optional[str]


@dataclass(frozen=True)
class RouteAssets:
    ssr: str            # path relative to dist/, e.g. "ssr/todos.mjs"
    client: str          # path relative to dist/, e.g. "client/todos.A1B2.js"
    css: Optional[str]  # path relative to dist/, or None if no styles
    preload: List[str] = field(default_factory=list)
    layout_chain: List[LayoutRefAsset] = field(default_factory=list)
    uses_layout_shell: bool = False


@dataclass(frozen=True)
class LayoutAssets:
    client: str          # hashed client module path, relative to dist/
    css: Optional[str]


@dataclass(frozen=True)
class RemoteModuleAssets:
    hash: str
    fns: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class Manifest:
    routes: Dict[str, RouteAssets]
    build_time: str = ""
    remote_modules: Dict[str, RemoteModuleAssets] = field(default_factory=dict)
    layouts: Dict[str, LayoutAssets] = field(default_factory=dict)
    global_css: Optional[str] = None

    def write(self, path: Path) -> None:
        data = {
            "version": MANIFEST_VERSION,
            "buildTime": self.build_time,
            "routes": {name: asdict(r) for name, r in self.routes.items()},
            "remote_modules": {name: asdict(m) for name, m in self.remote_modules.items()},
            "layouts": {name: asdict(l) for name, l in self.layouts.items()},
            "global_css": self.global_css,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.replace(tmp, path)

    @classmethod
    def read(cls, path: Path) -> Optional["Manifest"]:
        if not path.is_file():
            return None
        data = json.loads(path.read_text())
        if data.get("version") != MANIFEST_VERSION:
            raise ValueError(
                f"manifest.json version {data.get('version')} unsupported "
                f"(expected {MANIFEST_VERSION}); rebuild with `fymo build`"
            )
        routes = {
            name: RouteAssets(
                ssr=r["ssr"],
                client=r["client"],
                css=r.get("css"),
                preload=list(r.get("preload", [])),
                layout_chain=[
                    LayoutRefAsset(level=lr["level"], id=lr["id"], controller_module=lr.get("controller_module"))
                    for lr in r.get("layout_chain", [])
                ],
                uses_layout_shell=bool(r.get("uses_layout_shell", False)),
            )
            for name, r in data.get("routes", {}).items()
        }
        remote_modules = {
            name: RemoteModuleAssets(hash=m["hash"], fns=list(m.get("fns", [])))
            for name, m in data.get("remote_modules", {}).items()
        }
        layouts = {
            name: LayoutAssets(client=l["client"], css=l.get("css"))
            for name, l in data.get("layouts", {}).items()
        }
        return cls(
            routes=routes,
            build_time=data.get("buildTime", ""),
            remote_modules=remote_modules,
            layouts=layouts,
            global_css=data.get("global_css"),
        )
