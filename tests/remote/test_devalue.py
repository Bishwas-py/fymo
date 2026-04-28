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


def test_list_of_strings():
    out = devalue.stringify(["a", "b", "c"])
    assert devalue.parse(out) == ["a", "b", "c"]


def test_nested_list():
    val = [[1, 2], [3, 4]]
    assert devalue.parse(devalue.stringify(val)) == val


def test_dict_of_primitives():
    val = {"name": "alice", "age": 30, "active": True}
    assert devalue.parse(devalue.stringify(val)) == val


def test_nested_dict():
    val = {"user": {"name": "alice", "tags": ["x", "y"]}}
    assert devalue.parse(devalue.stringify(val)) == val


def test_tuple_round_trips_as_list():
    """devalue has no tuple type; tuples encode as arrays and round-trip as lists."""
    assert devalue.parse(devalue.stringify((1, 2, 3))) == [1, 2, 3]


def test_empty_list():
    assert devalue.parse(devalue.stringify([])) == []


def test_empty_dict():
    assert devalue.parse(devalue.stringify({})) == {}


def test_list_root_indices():
    """A list at root: arr[0]=1, arr[1]=[idx_of_a, idx_of_b], arr[2]='a', arr[3]='b'."""
    out = devalue.stringify(["a", "b"])
    arr = json.loads(out)
    assert arr[0] == 1
    # arr[1] is a list of indices pointing to "a" and "b"
    indices = arr[1]
    assert isinstance(indices, list) and len(indices) == 2
    assert arr[indices[0]] == "a"
    assert arr[indices[1]] == "b"
