"""Tests for the generated $broadcast client (.js + .d.ts per module)."""
from pathlib import Path

import pytest

from fymo.broadcast.codegen import emit_broadcast_module, emit_broadcast_runtime
from fymo.broadcast.discovery import discover_broadcast_channels


@pytest.fixture
def channels(tmp_path: Path):
    bdir = tmp_path / "app" / "broadcasts"
    bdir.mkdir(parents=True)
    (tmp_path / "app" / "__init__.py").touch()
    (bdir / "__init__.py").touch()
    (bdir / "runs.py").write_text(
        "from typing import TypedDict\n"
        "\n"
        "class RunStatusEvent(TypedDict):\n"
        "    status: str\n"
        "    run_video: str\n"
        "\n"
        "def run_status(run_id: str) -> RunStatusEvent:\n"
        "    ...\n"
    )
    return discover_broadcast_channels(tmp_path)


def test_emits_js_with_subscribe_functions(channels, tmp_path: Path):
    out = tmp_path / "out"
    emit_broadcast_module("runs", {"run_status": channels["run_status"][1]}, out)
    js = (out / "runs.js").read_text()
    assert "import { __subscribe } from './__runtime.js';" in js
    assert "run_status:" in js
    assert "__subscribe('runs', 'run_status'" in js


def test_emits_dts_with_typed_args_and_payload(channels, tmp_path: Path):
    out = tmp_path / "out"
    emit_broadcast_module("runs", {"run_status": channels["run_status"][1]}, out)
    dts = (out / "runs.d.ts").read_text()
    assert "export interface RunStatusEvent" in dts
    assert "status: string;" in dts
    assert "run_status(args: { run_id: string }, onEvent: (data: RunStatusEvent) => void): () => void;" in dts


def test_emits_runtime_with_eventsource_client(tmp_path: Path):
    emit_broadcast_runtime(tmp_path)
    runtime = (tmp_path / "__runtime.js").read_text()
    assert "EventSource" in runtime
    assert "/_fymo/broadcast/" in runtime
    assert "JSON.parse" in runtime
