"""devalue serialization — wire-compatible with the JS `devalue` package (v5+).

Format:
- Sentinels at root produce bare numbers: '-1' (undefined), '-3' (NaN),
  '-4' (Infinity), '-5' (-Infinity), '-6' (-0).
- All other roots produce a JSON array. Index 0 holds the encoded ROOT.
  Subsequent indices hold referenced values.
- An "encoded" value is one of:
    * a plain scalar (str/number/bool/null),
    * an array of ints `[i,...]` (a list, each int is a slot index),
    * an object `{k:i}` (a dict),
    * a tagged form like `["Date", iso]` or `["Set", i, ...]`.
"""
import base64
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import BaseModel

from fymo.remote import devalue


# ---------- scalars ----------

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


def test_string_root_inline():
    """'hello' at root → ['hello'] (length-1 array, scalar at slot 0)."""
    assert json.loads(devalue.stringify("hello")) == ["hello"]


def test_number_root_inline():
    assert json.loads(devalue.stringify(42)) == [42]


def test_null_root_inline():
    assert json.loads(devalue.stringify(None)) == [None]


def test_undefined_root_is_bare_sentinel():
    """undefined → bare '-1' (NOT in an array)."""
    assert devalue.stringify(devalue.UNDEFINED) == "-1"
    assert devalue.parse("-1") is devalue.UNDEFINED


def test_nan_root_is_bare_sentinel():
    out = devalue.stringify(float("nan"))
    assert out == "-3"
    parsed = devalue.parse(out)
    assert parsed != parsed  # NaN


def test_inf_root_is_bare_sentinel():
    assert devalue.stringify(float("inf")) == "-4"
    assert devalue.parse("-4") == float("inf")
    assert devalue.stringify(float("-inf")) == "-5"
    assert devalue.parse("-5") == float("-inf")


# ---------- containers ----------

def test_list_of_strings():
    assert devalue.parse(devalue.stringify(["a", "b", "c"])) == ["a", "b", "c"]


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
    assert devalue.parse(devalue.stringify((1, 2, 3))) == [1, 2, 3]


def test_empty_list():
    assert devalue.parse(devalue.stringify([])) == []
    # Wire shape: [[]]
    assert json.loads(devalue.stringify([])) == [[]]


def test_empty_dict():
    assert devalue.parse(devalue.stringify({})) == {}
    assert json.loads(devalue.stringify({})) == [{}]


def test_list_root_structural():
    """['a','b'] → [[1,2],'a','b'] — slot 0 is structural form (list of indices)."""
    arr = json.loads(devalue.stringify(["a", "b"]))
    indices = arr[0]
    assert isinstance(indices, list) and len(indices) == 2
    assert arr[indices[0]] == "a"
    assert arr[indices[1]] == "b"


def test_dict_root_structural():
    """{x:1} → [{x:1},1] — slot 0 has the dict's structural form, slot 1 has the value 1."""
    arr = json.loads(devalue.stringify({"x": 1}))
    structural = arr[0]
    assert isinstance(structural, dict) and "x" in structural
    assert arr[structural["x"]] == 1


def test_dedup_repeated_scalar():
    """[1,1,1] → [[1,1,1],1] — primitive 1 is stored once, referenced thrice."""
    arr = json.loads(devalue.stringify([1, 1, 1]))
    indices = arr[0]
    assert indices == [1, 1, 1]
    assert arr[1] == 1
    # Round-trip
    assert devalue.parse(devalue.stringify([1, 1, 1])) == [1, 1, 1]


# ---------- tagged types ----------

class Color(Enum):
    RED = "red"
    BLUE = "blue"


def test_datetime_round_trip_as_date():
    val = datetime(2026, 4, 28, 12, 0, 0, tzinfo=timezone.utc)
    arr = json.loads(devalue.stringify(val))
    assert arr[0][0] == "Date"
    parsed = devalue.parse(devalue.stringify(val))
    assert isinstance(parsed, datetime)
    assert parsed == val


def test_date_round_trips_as_iso_date():
    val = date(2026, 4, 28)
    parsed = devalue.parse(devalue.stringify(val))
    assert isinstance(parsed, date)
    assert parsed == val


def test_decimal_encodes_as_number():
    parsed = devalue.parse(devalue.stringify(Decimal("3.14")))
    assert parsed == 3.14


def test_uuid_round_trips_as_string():
    val = UUID("12345678-1234-5678-1234-567812345678")
    assert devalue.parse(devalue.stringify(val)) == str(val)


def test_bytes_round_trip_as_base64_string():
    val = b"hello world"
    parsed = devalue.parse(devalue.stringify(val))
    assert parsed == base64.b64encode(val).decode("ascii")


def test_str_enum_encodes_as_value():
    assert devalue.parse(devalue.stringify(Color.RED)) == "red"


# ---------- sets ----------

def test_set_round_trip():
    val = {"a", "b", "c"}
    parsed = devalue.parse(devalue.stringify(val))
    assert isinstance(parsed, set)
    assert parsed == val


def test_frozenset_round_trip():
    val = frozenset([1, 2, 3])
    parsed = devalue.parse(devalue.stringify(val))
    assert isinstance(parsed, set)
    assert parsed == set(val)


def test_set_tagged_format():
    """{x:1,y:2,z:3} → [['Set',i,i,i],1,2,3] — first slot is the tagged form."""
    arr = json.loads(devalue.stringify({1, 2, 3}))
    assert arr[0][0] == "Set"
    indices = arr[0][1:]
    decoded = sorted(arr[i] for i in indices)
    assert decoded == [1, 2, 3]


# ---------- pydantic + dedup + cycles ----------

class Item(BaseModel):
    sku: str
    qty: int


def test_pydantic_model_round_trips_as_dict():
    item = Item(sku="abc", qty=3)
    parsed = devalue.parse(devalue.stringify(item))
    assert parsed == {"sku": "abc", "qty": 3}


def test_dedup_repeated_dict_reference():
    """{a:i, b:i} where i is shared — inner dict appears once on the wire."""
    inner = {"x": 1}
    outer = {"a": inner, "b": inner}
    parsed = devalue.parse(devalue.stringify(outer))
    assert parsed == {"a": {"x": 1}, "b": {"x": 1}}
    arr = json.loads(devalue.stringify(outer))
    inner_dicts = [v for v in arr if isinstance(v, dict) and "x" in v]
    assert len(inner_dicts) == 1


def test_cyclic_reference_does_not_infinite_loop():
    """{self: itself} → [{self:0}] (slot 0 references itself)."""
    a: dict = {}
    a["self"] = a
    out = devalue.stringify(a)
    parsed = devalue.parse(out)
    assert parsed["self"] is parsed
