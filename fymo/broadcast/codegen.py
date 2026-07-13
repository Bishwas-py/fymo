"""Generate the $broadcast client — .js (EventSource wrappers) + .d.ts
(typed declarations) per app/broadcasts module, mirroring $remote codegen.

The generated surface:

    import { subscribe } from '$broadcast/runs';
    const unsubscribe = subscribe.run_status({ run_id }, (data) => { ... });

Channel args come from the channel function's signature; the callback's
payload type from its return annotation. JSON on the wire (SSE `data:`
frames), so payload types should stay JSON-shaped.
"""
from __future__ import annotations

import inspect
import typing
from pathlib import Path
from typing import Callable, Dict

from fymo.remote.typemap import python_type_to_ts

_RUNTIME_JS = '''// AUTO-GENERATED. Do not edit. Fymo broadcasts client runtime.

export function __subscribe(module, channel, args, onEvent) {
    const qs = new URLSearchParams(args ?? {}).toString();
    const url = `/_fymo/broadcast/${module}/${channel}` + (qs ? `?${qs}` : "");
    const es = new EventSource(url);
    es.onmessage = (e) => onEvent(JSON.parse(e.data));
    // EventSource auto-reconnects on transient drops. A 403/404 closes it
    // for good (readyState CLOSED) — surface nothing; the subscription is
    // simply over, matching fire-and-forget semantics.
    return () => es.close();
}
'''


def emit_broadcast_client(project_root: Path, dist_dir: Path) -> None:
    """Discover app/broadcasts/*.py and emit the full $broadcast client to
    dist/client/_broadcast/. One entry point shared by BuildPipeline AND
    DevOrchestrator so the two build paths can't drift (the $remote codegen
    wiring drifted once — dev builds silently lacked remote stubs)."""
    from fymo.broadcast.discovery import discover_broadcast_channels

    channels = discover_broadcast_channels(project_root)
    if not channels:
        return
    out = dist_dir / "client" / "_broadcast"
    emit_broadcast_runtime(out)
    by_module: Dict[str, Dict[str, Callable]] = {}
    for name, (module, fn) in channels.items():
        by_module.setdefault(module, {})[name] = fn
    for module, module_channels in by_module.items():
        emit_broadcast_module(module, module_channels, out)


def emit_broadcast_runtime(out_dir: Path) -> None:
    """Write the shared $broadcast client runtime file."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "__runtime.js").write_text(_RUNTIME_JS)


def _format_channel_dts(name: str, fn: Callable, type_defs: dict) -> str:
    hints = typing.get_type_hints(fn)
    params = []
    for pname, param in inspect.signature(fn).parameters.items():
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            raise ValueError(f"broadcast channel {name}: *args / **kwargs not supported")
        ts = python_type_to_ts(hints.get(pname, str), type_defs=type_defs)
        optional = "?" if param.default is not inspect.Parameter.empty else ""
        params.append(f"{pname}{optional}: {ts}")
    payload_ts = python_type_to_ts(hints.get("return", type(None)), type_defs=type_defs)
    args_ts = "{ " + ", ".join(params) + " }" if params else "Record<string, never>"
    return f"  {name}(args: {args_ts}, onEvent: (data: {payload_ts}) => void): () => void;"


def emit_broadcast_module(module_name: str, channels: Dict[str, Callable], out_dir: Path) -> None:
    """Write <out_dir>/<module_name>.js and .d.ts for one app/broadcasts
    module. `channels` maps channel name -> channel function (only the
    channels declared in this module)."""
    out_dir.mkdir(parents=True, exist_ok=True)

    type_defs: dict = {}
    dts_channel_lines = [_format_channel_dts(name, fn, type_defs) for name, fn in channels.items()]

    dts_lines = [f"// AUTO-GENERATED. Do not edit. Source: app/broadcasts/{module_name}.py", ""]
    for tname in sorted(type_defs):
        body = type_defs[tname]
        if body.startswith("{"):
            dts_lines.append(f"export interface {tname} {body}")
        else:
            dts_lines.append(f"export type {tname} = {body};")
        dts_lines.append("")
    dts_lines.append("export const subscribe: {")
    dts_lines.extend(dts_channel_lines)
    dts_lines.append("};")
    (out_dir / f"{module_name}.d.ts").write_text("\n".join(dts_lines) + "\n")

    js_lines = [
        f"// AUTO-GENERATED. Do not edit. Source: app/broadcasts/{module_name}.py",
        "import { __subscribe } from './__runtime.js';",
        "",
        "export const subscribe = {",
    ]
    for name in channels:
        js_lines.append(
            f"    {name}: (args, onEvent) => __subscribe('{module_name}', '{name}', args, onEvent),"
        )
    js_lines.append("};")
    (out_dir / f"{module_name}.js").write_text("\n".join(js_lines) + "\n")
