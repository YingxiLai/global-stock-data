"""Strict stdlib validation of the published DecisionRecord contract subset."""

import copy
import json
import re
from functools import cache
from importlib.resources import files
from pathlib import Path
from typing import Any

from .errors import DataError, require


@cache
def _decision_schema() -> dict[str, Any]:
    resource = files("global_stock_data").joinpath("contracts-v1.json")
    # Wheels include the canonical schema. Editable checkouts read that same
    # fixed repository file; no caller-controlled path or remote resolution.
    text = (
        resource.read_text()
        if resource.is_file()
        else (Path(__file__).resolve().parents[2] / "schemas/contracts-v1.json").read_text()
    )
    result: dict[str, Any] = json.loads(text)["$defs"]["DecisionRecord"]
    return result


def decision_schema() -> dict[str, Any]:
    return copy.deepcopy(_decision_schema())


def _failure(value: Any, rule: dict[str, Any], path: str = "record") -> str | None:
    """Only the schema keywords used by DecisionRecord; unknown rules fail closed."""
    require(
        set(rule)
        <= {
            "type",
            "required",
            "properties",
            "additionalProperties",
            "const",
            "enum",
            "minimum",
            "minLength",
            "maxLength",
            "pattern",
            "allOf",
            "if",
            "then",
            "else",
        },
        "Unsupported DecisionRecord contract keyword",
        "config",
    )
    native_types = {
        "object": dict,
        "string": str,
        "integer": int,
        "boolean": bool,
        "null": type(None),
    }
    if "type" in rule:
        kinds = rule["type"] if isinstance(rule["type"], list) else [rule["type"]]
        # Native exact-int representation excludes bool and coerced versions.
        if not any(type(value) is native_types[kind] for kind in kinds):
            return path
    for keyword, choices in (("const", [rule.get("const")]), ("enum", rule.get("enum", []))):
        if keyword in rule and not any(
            type(value) is type(choice) and value == choice for choice in choices
        ):
            return path
    if isinstance(value, str):
        if len(value) < rule.get("minLength", 0) or len(value) > rule.get("maxLength", len(value)):
            return path
        if "pattern" in rule and re.search(rule["pattern"], value) is None:
            return path
    if "minimum" in rule and type(value) is int and value < rule["minimum"]:
        return path
    if isinstance(value, dict):
        for key in rule.get("required", []):
            if key not in value:
                return str(key)
        properties = rule.get("properties", {})
        if rule.get("additionalProperties") is False and set(value) - set(properties):
            return path
        for key, child in properties.items():
            if key in value and (failure := _failure(value[key], child, key)) is not None:
                return failure
    for child in rule.get("allOf", []):
        if (failure := _failure(value, child, path)) is not None:
            return failure
    if "if" in rule:
        branch = "then" if _failure(value, rule["if"], path) is None else "else"
        if branch in rule:
            return _failure(value, rule[branch], path)
    return None


def validate_decision_record(item: Any) -> None:
    failure = _failure(item, _decision_schema())
    if failure is not None:
        code = (
            "approval_required"
            if failure
            in (
                "user_approved",
                "actor",
                "state",
                "confirmation_ref",
                "execution_status",
            )
            else "schema"
        )
        raise DataError(code, "Invalid DecisionRecord contract field: " + failure)
