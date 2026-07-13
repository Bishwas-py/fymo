"""The generated client's payload encoder must handle Unicode.

`btoa` only accepts Latin1, so any remote-call argument containing an emoji,
em-dash, accent, or CJK character used to throw in the browser before the
request was sent. This runs the actual emitted `b64url` in Node and checks it
round-trips through the Python server-side decoder.
"""
import re
import subprocess

import pytest

from fymo.remote.codegen import _RUNTIME_JS
from fymo.remote.router import _b64url_decode


def _extract_b64url() -> str:
    m = re.search(r"function b64url\(s\) \{.*?\n\}", _RUNTIME_JS, re.S)
    assert m, "b64url function not found in the generated runtime"
    return m.group(0)


@pytest.mark.usefixtures("node_available")
def test_b64url_roundtrips_unicode(tmp_path):
    text = "em—dash, café, 日本語, 🚀"
    script = _extract_b64url() + "\nprocess.stdout.write(b64url(process.argv[2]));\n"
    entry = tmp_path / "enc.mjs"
    entry.write_text(script)

    proc = subprocess.run(
        ["node", str(entry), text], capture_output=True, text=True
    )
    assert proc.returncode == 0, f"encoder threw on Unicode: {proc.stderr}"
    # The server decodes base64url -> bytes -> utf-8; it must recover the input.
    assert _b64url_decode(proc.stdout) == text


@pytest.mark.usefixtures("node_available")
def test_b64url_still_handles_ascii(tmp_path):
    text = "plain ascii payload"
    script = _extract_b64url() + "\nprocess.stdout.write(b64url(process.argv[2]));\n"
    entry = tmp_path / "enc.mjs"
    entry.write_text(script)

    proc = subprocess.run(["node", str(entry), text], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert _b64url_decode(proc.stdout) == text
