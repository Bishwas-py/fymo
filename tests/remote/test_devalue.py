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


from datetime import datetime, date, timezone
from decimal import Decimal
from enum import Enum
from uuid import UUID


class Color(Enum):
    RED = "red"
    BLUE = "blue"


def test_datetime_round_trip_as_date():
    """datetime → ['Date', '<iso>']; client receives a JS Date.
    We round-trip it to a Python datetime."""
    val = datetime(2026, 4, 28, 12, 0, 0, tzinfo=timezone.utc)
    out = devalue.stringify(val)
    # Tagged shape: arr[1] should be ["Date", "<iso>"]
    arr = json.loads(out)
    assert arr[arr[0]][0] == "Date"
    parsed = devalue.parse(out)
    assert isinstance(parsed, datetime)
    assert parsed == val


def test_date_round_trips_as_iso_date():
    val = date(2026, 4, 28)
    parsed = devalue.parse(devalue.stringify(val))
    assert isinstance(parsed, date)
    assert parsed == val


def test_decimal_encodes_as_number():
    """Decimal becomes a number on the JS side; we lose Decimal precision but match SvelteKit."""
    parsed = devalue.parse(devalue.stringify(Decimal("3.14")))
    assert parsed == 3.14


def test_uuid_round_trips_as_string():
    val = UUID("12345678-1234-5678-1234-567812345678")
    parsed = devalue.parse(devalue.stringify(val))
    assert parsed == str(val)


def test_bytes_round_trip_as_base64_string():
    val = b"hello world"
    parsed = devalue.parse(devalue.stringify(val))
    # Bytes go over the wire as base64 strings; caller decodes if needed.
    import base64
    assert parsed == base64.b64encode(val).decode("ascii")


def test_str_enum_encodes_as_value():
    parsed = devalue.parse(devalue.stringify(Color.RED))
    assert parsed == "red"


def test_set_round_trip():
    val = {"a", "b", "c"}
    parsed = devalue.parse(devalue.stringify(val))
    assert isinstance(parsed, set)
    assert parsed == val


def test_frozenset_round_trip():
    val = frozenset([1, 2, 3])
    parsed = devalue.parse(devalue.stringify(val))
    assert isinstance(parsed, set)  # Decodes back as plain set
    assert parsed == set(val)


def test_set_tagged_format():
    out = devalue.stringify({"x"})
    arr = json.loads(out)
    assert arr[arr[0]][0] == "Set"


from pydantic import BaseModel


class Item(BaseModel):
    sku: str
    qty: int


def test_pydantic_model_round_trips_as_dict():
    """Pydantic models go through model_dump and round-trip as plain dicts."""
    item = Item(sku="abc", qty=3)
    parsed = devalue.parse(devalue.stringify(item))
    assert parsed == {"sku": "abc", "qty": 3}


def test_dedup_repeated_dict_reference():
    """Same dict referenced twice should encode once and be deduplicated."""
    inner = {"x": 1}
    outer = {"a": inner, "b": inner}
    parsed = devalue.parse(devalue.stringify(outer))
    assert parsed == {"a": {"x": 1}, "b": {"x": 1}}
    # And on the wire, the inner dict only appears once
    out = devalue.stringify(outer)
    arr = json.loads(out)
    inner_dicts = [v for v in arr[1:] if isinstance(v, dict) and "x" in v]
    assert len(inner_dicts) == 1


def test_cyclic_reference_does_not_infinite_loop():
    """A self-referencing structure should encode without recursion error."""
    a: dict = {}
    a["self"] = a
    out = devalue.stringify(a)
    parsed = devalue.parse(out)
    assert parsed["self"] is parsed  # Reconstructed cycle
