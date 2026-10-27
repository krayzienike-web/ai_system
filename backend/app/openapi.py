"""The API contract for the frontend (ADR 0007): the OpenAPI schema and TypeScript types generated from it.

`python -m app.openapi` writes `frontend/src/api/openapi.json` and `frontend/src/api/schema.ts`; CI checks
that both are up to date, so the screens and the prototype's recorded answers use the shapes the API returns.
"""

import json
from pathlib import Path
from typing import Any

from app.main import app

FRONTEND_API = Path(__file__).resolve().parents[2] / "frontend" / "src" / "api"


def _name(ref: str) -> str:
    return ref.rsplit("/", 1)[-1].replace("-", "_")


def ts_type(s: dict[str, Any]) -> str:
    if "$ref" in s:
        return _name(s["$ref"])
    if "enum" in s:
        return " | ".join(json.dumps(v, ensure_ascii=False) for v in s["enum"])
    if "const" in s:
        return json.dumps(s["const"], ensure_ascii=False)
    for key in ("anyOf", "oneOf"):
        if key in s:
            parts = []
            for p in s[key]:
                t = ts_type(p)
                if t not in parts:
                    parts.append(t)
            return " | ".join(parts)
    kind = s.get("type")
    if kind == "array":
        item = ts_type(s.get("items", {}))
        return f"({item})[]" if "|" in item else f"{item}[]"
    if kind == "object" or "properties" in s:
        if "properties" in s:
            return _object(s, indent="  ")
        extra = s.get("additionalProperties")
        return f"Record<string, {ts_type(extra) if isinstance(extra, dict) else 'unknown'}>"
    return {
        "string": "string",
        "integer": "number",
        "number": "number",
        "boolean": "boolean",
        "null": "null",
    }.get(kind or "", "unknown")


def _object(s: dict[str, Any], indent: str = "") -> str:
    required = set(s.get("required", []))
    lines = []
    for prop, schema in s.get("properties", {}).items():
        doc = schema.get("description")
        if doc:
            lines.append(f"{indent}  /** {doc} */")
        optional = "" if prop in required else "?"
        lines.append(f"{indent}  {prop}{optional}: {ts_type(schema)};")
    return "{\n" + "\n".join(lines) + f"\n{indent}}}"


def typescript(schema: dict[str, Any]) -> str:
    out = [
        "// Generated from the API's OpenAPI schema by `python -m app.openapi` (backend). Do not edit.",
        "",
    ]
    for name, s in sorted(schema.get("components", {}).get("schemas", {}).items()):
        ts_name = _name(name)
        doc = s.get("description")
        if doc:
            out.append("/** " + doc.replace("*/", "* /").replace("\n", "\n * ") + " */")
        if s.get("type") == "object" or "properties" in s:
            out.append(f"export interface {ts_name} {_object(s)}")
        else:
            out.append(f"export type {ts_name} = {ts_type(s)};")
        out.append("")
    return "\n".join(out)


def main() -> None:
    schema = app.openapi()
    (FRONTEND_API / "openapi.json").write_text(
        json.dumps(schema, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    (FRONTEND_API / "schema.ts").write_text(typescript(schema), encoding="utf-8")


if __name__ == "__main__":
    main()
