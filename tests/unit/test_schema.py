"""Tests for stdlib JSON Schema validator in lilly.domain.schema."""
from __future__ import annotations

import pytest

from lilly.domain.schema import SchemaValidationError, validate, validate_schema


def test_schema_types_valid() -> None:
    schema = {
        "type": "object",
        "properties": {
            "str_val": {"type": "string"},
            "int_val": {"type": "integer"},
            "num_val": {"type": "number"},
            "bool_val": {"type": "boolean"},
            "arr_val": {"type": "array"},
            "obj_val": {"type": "object"},
            "null_val": {"type": "null"},
        },
    }
    data = {
        "str_val": "hello",
        "int_val": 42,
        "num_val": 3.14,
        "bool_val": True,
        "arr_val": [1, 2, 3],
        "obj_val": {"a": 1},
        "null_val": None,
    }
    assert validate_schema(schema, data) == []
    validate(schema, data)


def test_schema_types_invalid() -> None:
    schema = {"type": "integer"}
    # bool is not considered integer
    errs = validate_schema(schema, True, path="val")
    assert errs == ["val: expected integer, got boolean"]

    errs = validate_schema(schema, "42", path="val")
    assert errs == ["val: expected integer, got string"]

    errs = validate_schema(schema, 3.14, path="val")
    assert errs == ["val: expected integer, got number"]


def test_schema_required_fields() -> None:
    schema = {
        "type": "object",
        "required": ["path", "content"],
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
    }
    errs = validate_schema(schema, {"path": "a.txt"})
    assert errs == ["args.content: required"]

    with pytest.raises(SchemaValidationError) as exc_info:
        validate(schema, {})
    assert "args.path: required" in str(exc_info.value)
    assert "args.content: required" in str(exc_info.value)


def test_schema_enum() -> None:
    schema = {"type": "string", "enum": ["auto", "none", "required"]}
    assert validate_schema(schema, "auto", path="choice") == []

    errs = validate_schema(schema, "invalid", path="choice")
    assert errs == ["choice: must be one of ['auto', 'none', 'required']"]


def test_schema_min_max_numbers() -> None:
    schema = {"type": "number", "minimum": 1, "maximum": 10}
    assert validate_schema(schema, 5, path="num") == []
    assert validate_schema(schema, 1, path="num") == []
    assert validate_schema(schema, 10, path="num") == []

    errs = validate_schema(schema, 0, path="num")
    assert errs == ["num: must be >= 1"]

    errs = validate_schema(schema, 11, path="num")
    assert errs == ["num: must be <= 10"]


def test_schema_min_max_strings() -> None:
    schema = {"type": "string", "minLength": 2, "maxLength": 5}
    assert validate_schema(schema, "abc", path="str") == []
    assert validate_schema(schema, "a", path="str") == ["str: must be at least 2 characters"]
    assert validate_schema(schema, "abcdef", path="str") == ["str: must be at most 5 characters"]


def test_schema_nested_objects_and_additional_properties() -> None:
    schema = {
        "type": "object",
        "properties": {
            "user": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        "additionalProperties": False,
    }
    valid_data = {"user": {"name": "Alice"}}
    assert validate_schema(schema, valid_data) == []

    # Extra property at top level
    errs = validate_schema(schema, {"user": {"name": "Alice"}, "extra": 123})
    assert errs == ["args.extra: unexpected field"]

    # Extra property inside user
    errs = validate_schema(schema, {"user": {"name": "Alice", "age": 30}})
    assert errs == ["args.user.age: unexpected field"]

    # Missing required property inside user
    errs = validate_schema(schema, {"user": {}})
    assert errs == ["args.user.name: required"]


def test_schema_array_items() -> None:
    schema = {
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
    }
    assert validate_schema(schema, {"todos": ["task 1", "task 2"]}) == []

    errs = validate_schema(schema, {"todos": ["task 1", 123, True]})
    assert errs == [
        "args.todos[1]: expected string, got integer",
        "args.todos[2]: expected string, got boolean",
    ]


def test_schema_additional_properties_schema() -> None:
    schema = {
        "type": "object",
        "properties": {"fixed": {"type": "string"}},
        "additionalProperties": {"type": "integer"},
    }
    assert validate_schema(schema, {"fixed": "val", "any_int": 42}) == []
    errs = validate_schema(schema, {"fixed": "val", "bad_extra": "not an int"})
    assert errs == ["args.bad_extra: expected integer, got string"]
