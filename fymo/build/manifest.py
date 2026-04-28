"""dist/manifest.json read/write contract between build and runtime."""
import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional


MANIFEST_VERSION = 1


@dataclass(frozen=True)
class RouteAssets:
    ssr: str            # path relative to dist/, e.g. "ssr/todos.mjs"
    client: str         # path relative to dist/, e.g. "client/todos.A1B2.js"
    css: Optional[str]  # path relative to dist/, or None if no styles
    preload: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class RemoteModuleAssets:
    hash: str
    fns: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class Manifest:
    routes: Dict[str, RouteAssets]
    build_time: str = ""
    remote_modules: Dict[str, RemoteModuleAssets] = field(default_factory=dict)

    def write(self, path: Path) -> None:
        data = {
            "version": MANIFEST_VERSION,
            "buildTime": self.build_time,
            "routes": {name: asdict(r) for name, r in self.routes.items()},
            "remote_modules": {name: asdict(m) for name, m in self.remote_modules.items()},
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
            )
            for name, r in data.get("routes", {}).items()
        }
        remote_modules = {
            name: RemoteModuleAssets(hash=m["hash"], fns=list(m.get("fns", [])))
            for name, m in data.get("remote_modules", {}).items()
        }
        return cls(routes=routes, build_time=data.get("buildTime", ""), remote_modules=remote_modules)
