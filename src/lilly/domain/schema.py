"""Small stdlib JSON-Schema validator for Lilly tool arguments.

Supports type, required, enum, minimum, maximum, items, properties, and additionalProperties.
Returns clear error paths like 'args.path: required' with zero external dependencies.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class SchemaValidationError(Exception):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


def validate_schema(schema: Mapping[str, Any], data: Any, path: str = "args") -> list[str]:
    """Validate data against a JSON Schema, returning a list of error strings.
    
    Empty list means validation succeeded.
    """
    errors: list[str] = []

    # 1. Type validation
    expected_type = schema.get("type")
    if expected_type is not None:
        if isinstance(expected_type, str):
            types = [expected_type]
        elif isinstance(expected_type, (list, tuple)):
            types = list(expected_type)
        else:
            types = []

        type_match = False
        for t in types:
            if t == "object" and isinstance(data, dict):
                type_match = True
            elif t == "array" and isinstance(data, list):
                type_match = True
            elif t == "string" and isinstance(data, str):
                type_match = True
            elif t == "integer" and isinstance(data, int) and not isinstance(data, bool):
                type_match = True
            elif t == "number" and isinstance(data, (int, float)) and not isinstance(data, bool):
                type_match = True
            elif t == "boolean" and isinstance(data, bool):
                type_match = True
            elif t == "null" and data is None:
                type_match = True

        if not type_match:
            actual_type = type(data).__name__
            if isinstance(data, bool):
                actual_type = "boolean"
            elif isinstance(data, int):
                actual_type = "integer"
            elif isinstance(data, float):
                actual_type = "number"
            elif isinstance(data, str):
                actual_type = "string"
            elif isinstance(data, list):
                actual_type = "array"
            elif isinstance(data, dict):
                actual_type = "object"
            elif data is None:
                actual_type = "null"
            expected_desc = " or ".join(types)
            errors.append(f"{path}: expected {expected_desc}, got {actual_type}")
            return errors  # type failed, cannot validate inner constraints

    # 2. Enum
    if "enum" in schema:
        allowed = schema["enum"]
        if data not in allowed:
            errors.append(f"{path}: must be one of {allowed!r}")

    # 3. Numbers: minimum / maximum
    if isinstance(data, (int, float)) and not isinstance(data, bool):
        if "minimum" in schema and data < schema["minimum"]:
            errors.append(f"{path}: must be >= {schema['minimum']}")
        if "maximum" in schema and data > schema["maximum"]:
            errors.append(f"{path}: must be <= {schema['maximum']}")

    # 4. Strings: minLength / maxLength
    if isinstance(data, str):
        if "minLength" in schema and len(data) < schema["minLength"]:
            errors.append(f"{path}: must be at least {schema['minLength']} characters")
        if "maxLength" in schema and len(data) > schema["maxLength"]:
            errors.append(f"{path}: must be at most {schema['maxLength']} characters")

    # 5. Objects: required, properties, additionalProperties
    if isinstance(data, dict):
        required = schema.get("required", ())
        for req_prop in required:
            if req_prop not in data:
                sub_path = f"{path}.{req_prop}" if path else req_prop
                errors.append(f"{sub_path}: required")

        properties = schema.get("properties", {})
        for key, val in data.items():
            sub_path = f"{path}.{key}" if path else key
            if key in properties:
                prop_schema = properties[key]
                if isinstance(prop_schema, Mapping):
                    errors.extend(validate_schema(prop_schema, val, sub_path))
            elif schema.get("additionalProperties") is False:
                errors.append(f"{sub_path}: unexpected field")

        add_props = schema.get("additionalProperties")
        if isinstance(add_props, Mapping):
            for key, val in data.items():
                if key not in properties:
                    sub_path = f"{path}.{key}" if path else key
                    errors.extend(validate_schema(add_props, val, sub_path))

    # 6. Arrays: items
    if isinstance(data, list):
        items_schema = schema.get("items")
        if isinstance(items_schema, Mapping):
            for i, item in enumerate(data):
                errors.extend(validate_schema(items_schema, item, f"{path}[{i}]"))

    return errors


def validate(schema: Mapping[str, Any], data: Any, path: str = "args") -> None:
    """Validate data against a JSON Schema. Raises SchemaValidationError if invalid."""
    errors = validate_schema(schema, data, path=path)
    if errors:
        raise SchemaValidationError(errors)
