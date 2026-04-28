"""Generate .js (fetch wrappers) + .d.ts (typed declarations) per remote module."""
import inspect
from pathlib import Path
from fymo.remote.discovery import RemoteFunction
from fymo.remote.typemap import python_type_to_ts


_RUNTIME_JS = '''// AUTO-GENERATED. Do not edit. Fymo remote-functions client runtime.
import { stringify, parse } from 'devalue';

const REMOTE_MARKER = "__fymo_remote";

function b64url(s) {
    return btoa(s).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

export async function __rpc(hash, name, args) {
    const url = `/_fymo/remote/${hash}/${name}`;
    const payload = b64url(stringify(args));
    const res = await fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ payload }),
    });
    let env;
    try { env = await res.json(); }
    catch (e) { throw new Error("invalid response from " + url); }
    if (env.type === "redirect") {
        window.location.href = env.location;
        return;
    }
    if (env.type === "error") {
        const e = new Error(env.error || "remote_error");
        e.status = env.status;
        e.error = env.error;
        e.issues = env.issues;
        throw e;
    }
    return parse(env.result);
}

// Replaces marker objects in props (emitted by SSR) with real fetch wrappers.
export function __resolveRemoteProps(props) {
    for (const key in props) {
        const v = props[key];
        if (v && typeof v === "object" && v[REMOTE_MARKER]) {
            const sep = v[REMOTE_MARKER].indexOf("/");
            const hash = v[REMOTE_MARKER].slice(0, sep);
            const name = v[REMOTE_MARKER].slice(sep + 1);
            props[key] = (...args) => __rpc(hash, name, args);
        }
    }
    return props;
}
'''


def _format_function_dts(fn: RemoteFunction, type_defs: dict[str, str]) -> str:
    """Build the `export function name(...): Promise<R>;` line."""
    params = []
    for pname, param in fn.signature.parameters.items():
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            raise ValueError(f"{fn.module}.{fn.name}: *args / **kwargs not supported")
        ts = python_type_to_ts(fn.hints[pname], type_defs=type_defs)
        optional = "?" if param.default is not inspect.Parameter.empty else ""
        params.append(f"{pname}{optional}: {ts}")
    ret_hint = fn.hints.get("return", type(None))
    ret_ts = python_type_to_ts(ret_hint, type_defs=type_defs)
    return f"export function {fn.name}({', '.join(params)}): Promise<{ret_ts}>;"


def _format_function_js(fn: RemoteFunction) -> str:
    pnames = list(fn.signature.parameters.keys())
    params = ", ".join(pnames)
    args = "[" + ", ".join(pnames) + "]"
    return f"export const {fn.name} = ({params}) => __rpc(HASH, '{fn.name}', {args});"


def emit_module(module_name: str, fns: dict[str, RemoteFunction], out_dir: Path) -> None:
    """Write <out_dir>/<module_name>.js and <module_name>.d.ts."""
    out_dir.mkdir(parents=True, exist_ok=True)

    type_defs: dict[str, str] = {}
    dts_fn_lines: list[str] = []
    for fn in fns.values():
        dts_fn_lines.append(_format_function_dts(fn, type_defs))

    # Emit interfaces in a stable order
    dts_lines = [f"// AUTO-GENERATED. Do not edit. Source: app/remote/{module_name}.py", ""]
    for name in sorted(type_defs):
        body = type_defs[name]
        if body.startswith("{"):
            dts_lines.append(f"export interface {name} {body}")
        else:
            dts_lines.append(f"export type {name} = {body};")
        dts_lines.append("")
    dts_lines.extend(dts_fn_lines)
    (out_dir / f"{module_name}.d.ts").write_text("\n".join(dts_lines) + "\n")

    # Determine the hash from any fn (they all share the same module_hash)
    any_fn = next(iter(fns.values()))
    js_lines = [
        f"// AUTO-GENERATED. Do not edit. Source: app/remote/{module_name}.py",
        "import { __rpc } from './__runtime.js';",
        f"const HASH = '{any_fn.module_hash}';",
        "",
    ]
    for fn in fns.values():
        js_lines.append(_format_function_js(fn))
    (out_dir / f"{module_name}.js").write_text("\n".join(js_lines) + "\n")


def emit_runtime(out_dir: Path) -> None:
    """Write the shared client runtime file."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "__runtime.js").write_text(_RUNTIME_JS)
