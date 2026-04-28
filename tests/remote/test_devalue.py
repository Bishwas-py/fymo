"""devalue serialization — primitives + sentinels.

Format reference: https://github.com/Rich-Harris/devalue
- Output is a JSON array of values.
- Index 0 holds the root reference.
- Subsequent indices hold values referenced by other entries.
- Negative integers are sentinels (-1=undefined, -2=null, -3=NaN, -4=Inf, -5=-Inf, -6=0).
"""
import json
from fymo.remote import devalue


def test_strings():
    assert devalue.parse(devalue.stringify("hello")) == "hello"


def test_numbers():
    assert devalue.parse(devalue.stringify(42)) == 42
    assert devalue.parse(devalue.stringify(3.14)) == 3.14
    assert devalue.parse(devalue.stringify(0)) == 0


def test_booleans():
    assert devalue.parse(devalue.stringify(True)) is True
    assert devalue.parse(devalue.stringify(False)) is False


def test_none_round_trips_as_null():
    assert devalue.parse(devalue.stringify(None)) is None


def test_string_root_at_index_one():
    """Output shape: '[1,"hello"]' — root reference is index 1."""
    out = devalue.stringify("hello")
    arr = json.loads(out)
    assert arr[0] == 1
    assert arr[1] == "hello"


def test_undefined_uses_sentinel_minus_one():
    """A field with the sentinel UNDEFINED encodes to -1, not present-as-null."""
    out = devalue.stringify(devalue.UNDEFINED)
    assert json.loads(out) == [-1]
