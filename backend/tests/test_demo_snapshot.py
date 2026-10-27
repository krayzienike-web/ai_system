"""TC-DEMO-05: the prototype's recorded answers still fit the API (ADR 0007).

The snapshot is recorded by `make demo-snapshot`; its ids differ on every recording, so it is not compared
byte by byte. Instead every recorded answer is checked against the OpenAPI schema of the route that gave it:
a field renamed, added or removed in the API without re-recording fails here.
"""

import json
import re
from pathlib import Path
from typing import Any

from app.demo.snapshot import OUT
from app.main import app

SCHEMA = app.openapi()
COMPONENTS = SCHEMA["components"]["schemas"]
TYPES: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
}


def response_schema(path: str, method: str) -> dict[str, Any]:
    url = f"/api{path.split('?')[0]}"
    for template, operations in SCHEMA["paths"].items():
        pattern = re.sub(r"\{[^}]+\}", "[^/]+", template)
        if re.fullmatch(pattern, url) and method in operations:
            content = operations[method]["responses"]["200"]["content"]
            schema: dict[str, Any] = content["application/json"]["schema"]
            return schema
    raise AssertionError(f"no route for {method.upper()} {path}")


def problems(value: Any, schema: dict[str, Any], where: str) -> list[str]:
    """What in `value` does not fit `schema`: missing or unknown fields, wrong types."""
    if "$ref" in schema:
        return problems(value, COMPONENTS[schema["$ref"].split("/")[-1]], where)
    if "anyOf" in schema:
        options = [problems(value, s, where) for s in schema["anyOf"]]
        return [] if any(not p for p in options) else min(options, key=len)
    kind = schema.get("type")
    if kind == "null":
        return [] if value is None else [f"{where}: expected null"]
    if kind == "array":
        if not isinstance(value, list):
            return [f"{where}: expected a list"]
        item_schema = schema.get("items", {})
        return [p for i, item in enumerate(value) for p in problems(item, item_schema, f"{where}[{i}]")]
    if kind == "object" or "properties" in schema:
        if not isinstance(value, dict):
            return [f"{where}: expected an object"]
        props = schema.get("properties")
        if props is None:  # a free-form dict
            extra = schema.get("additionalProperties")
            sub = extra if isinstance(extra, dict) else {}
            return [p for k, v in value.items() for p in problems(v, sub, f"{where}.{k}")]
        found = [f"{where}: missing {k}" for k in schema.get("required", []) if k not in value]
        found += [f"{where}: unknown {k}" for k in value if k not in props]
        inner = [p for k, v in value.items() if k in props for p in problems(v, props[k], f"{where}.{k}")]
        return found + inner
    wrong = kind in TYPES and not isinstance(value, TYPES[kind])
    if wrong or (kind in ("integer", "number", "string") and isinstance(value, bool)):
        return [f"{where}: expected {kind}"]
    return []


def snapshot() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(Path(OUT).read_text(encoding="utf-8"))
    return data


def test_recorded_answers_fit_the_api() -> None:
    found: list[str] = []
    checked = 0
    for email, user in snapshot()["users"].items():
        for path, answer in user["answers"].items():
            found += problems(answer, response_schema(path, "get"), f"{email} {path}")
            checked += 1
        chat = response_schema("/chat", "post")
        for question, answer in user["chat"].items():
            found += problems(answer, chat, f"{email} chat «{question}»")
    assert found == [], "re-record with `make demo-snapshot`:\n" + "\n".join(found[:20])
    assert checked > 200


def test_the_checker_notices_a_changed_field() -> None:
    schema = response_schema("/overview/badges", "get")
    good = snapshot()["users"]["admin@demo.local"]["answers"]["/overview/badges"]
    assert problems(good, schema, "") == []
    renamed = {f"{k}_old": v for k, v in good.items()}
    assert problems(renamed, schema, "")


def test_every_demo_user_is_recorded_with_the_screens_they_use() -> None:
    users = snapshot()["users"]
    assert set(users) == {
        "admin@demo.local",
        "analyst@demo.local",
        "director1@demo.local",
        "director2@demo.local",
        "director3@demo.local",
    }
    for email, user in users.items():
        hq = user["me"]["role"] != "restaurant_director"
        screens = {"/overview/findings", "/findings", "/tasks", "/overview/context"}
        assert screens <= set(user["answers"]), email
        assert ("/overview/network?preset=week" in user["answers"]) is hq, email
