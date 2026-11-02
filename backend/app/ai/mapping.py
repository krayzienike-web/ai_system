"""An unfamiliar export (ADR 0008, stage 5.5; docs/09, «Адаптивный импорт»): the assistant marks which column
is which, the import checks the marking on the file itself, a person confirms it once and it becomes a source
profile — later files with these headers load by it through the whole validation.

Order: the header row is found by the code; the template's synonyms and the network's profiles map what they
can; only the rest goes to the model, with the headers and a few sample rows. A marking the import cannot read
(no header, a required column missing, most rows in error) goes back to the model once, then there is no
proposal.
"""

import re
from datetime import date
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.ai.gateway import Gateway
from app.ai.suggestions import Proposal, ask, deciding, keep
from app.core.errors import ConflictError, InvalidError
from app.imports import service as imports
from app.imports.reader import HEADER_SEARCH_ROWS, map_header, norm_header, read_rows, read_table
from app.imports.templates import TEMPLATES, Template
from app.imports.validate import validate
from app.tenancy.context import AccessContext, user_session
from app.tenancy.permissions import Permission

SAMPLE_ROWS = 5
MOSTLY_BROKEN = 0.5  # a marking under which half of the rows fail is not a marking
NUMBERISH = re.compile(r"^[\d\s.,:/-]+$")


class Choice(BaseModel):
    field: str = Field(description="Колонка шаблона (name)")
    header: str = Field(description="Заголовок колонки файла, ровно как в файле")
    why: str = Field(description="Почему эта колонка — по заголовку и образцам")


class Marking(BaseModel):
    columns: list[Choice]


def guess_header(rows: list[list[str]]) -> int:
    """The header row of a file nobody knows yet: the first of the top rows that is mostly words and is
    followed by a row of values."""
    for i, cells in enumerate(rows[:HEADER_SEARCH_ROWS]):
        filled = [c.strip() for c in cells if c.strip()]
        words = [c for c in filled if not NUMBERISH.match(c)]
        nxt = rows[i + 1] if i + 1 < len(rows) else []
        if len(filled) >= 3 and len(words) >= len(filled) * 2 / 3 and sum(1 for c in nxt if c.strip()) >= 2:
            return i
    raise InvalidError("Не нашли строку заголовков: в первых строках файла нет строки с названиями колонок")


def _fields(t: Template) -> list[dict[str, Any]]:
    return [
        {"field": c.name, "title": c.title, "kind": c.kind.value, "required": c.required} for c in t.columns
    ]


def _try(
    session: Session,
    t: Template,
    raw: bytes,
    filename: str,
    aliases: dict[str, str],
    restaurant_id: UUID | None,
    today: date,
) -> dict[str, Any]:
    """The import read with this marking: how many rows it takes, the first errors, a few records."""
    table = read_table(raw, filename, t, aliases=aliases)
    result = validate(t, table, imports.load_lookups(session, restaurant_id), today=today)
    total = result.rows_total
    errors = result.errors
    bad_rows = len({i.row for i in errors})
    return {
        "rows": total,
        "rows_with_errors": bad_rows,
        "errors": [f"строка {i.row}: {i.message}" for i in errors[:5]],
        "header_row": table.header_row,
    }


def propose_marking(
    gateway: Gateway,
    ctx: AccessContext,
    *,
    template_name: str,
    restaurant_id: UUID | None,
    filename: str,
    raw: bytes,
    today: date,
) -> tuple[Proposal, dict[str, Any]]:
    if not ctx.can(Permission.DATA_UPLOAD):
        raise InvalidError("Размечать файлы может тот, кто загружает данные")
    t = TEMPLATES.get(template_name)
    if t is None:
        raise InvalidError(f"Неизвестный шаблон: {template_name}")
    rows = read_rows(raw, filename)
    index = guess_header(rows)
    headers = [c.strip() for c in rows[index] if c.strip()]
    with user_session(ctx) as session:
        imports.check_access(session, ctx, t, restaurant_id)
        aliases = imports.profile_aliases(session).get(t.name, {})
        known, _ = map_header(rows[index], t, aliases)
    already = {name: rows[index][i].strip() for name, i in known.items()}
    basis = {
        "template": t.title,
        "fields": _fields(t),
        "headers": headers,
        "samples": [[c.strip() for c in r] for r in rows[index + 1 : index + 1 + SAMPLE_ROWS]],
        "already_mapped": already,
    }
    preview: dict[str, Any] = {}

    def check(m: Marking) -> list[str]:
        names = {c.name for c in t.columns}
        problems = [f"нет колонки шаблона {c.field}" for c in m.columns if c.field not in names]
        problems += [f"нет заголовка «{c.header}» в файле" for c in m.columns if c.header not in headers]
        chosen = {**already, **{c.field: c.header for c in m.columns}}
        if len(set(chosen.values())) != len(chosen):
            problems.append("один заголовок отдан двум колонкам")
        if problems:
            return problems
        with user_session(ctx) as session:
            try:
                tried = _try(
                    session,
                    t,
                    raw,
                    filename,
                    {norm_header(h): f for f, h in chosen.items()},
                    restaurant_id,
                    today,
                )
            except InvalidError as e:
                return [str(e)]
        if tried["rows"] and tried["rows_with_errors"] / tried["rows"] > MOSTLY_BROKEN:
            bad, total = tried["rows_with_errors"], tried["rows"]
            return [f"с такой разметкой ошибки в {bad} строках из {total}: {'; '.join(tried['errors'])}"]
        preview.clear()
        preview.update(tried)
        return []

    result, chat = ask(
        gateway, ctx, task="mapping", prompt_name="mapping", basis=basis, answer=Marking, check=check
    )
    columns = [{"field": f, "header": h, "why": "по словарю синонимов"} for f, h in already.items()]
    columns += [c.model_dump() for c in result.columns if c.field not in already]
    content = {"template": t.name, "filename": filename[:300], "columns": columns, "preview": preview}
    (kept,) = keep(
        ctx,
        kind="mapping",
        subject_id=None,
        restaurant_id=restaurant_id,
        contents=[content],
        basis=basis,
        chat=chat,
    )
    return kept, preview


def confirm(ctx: AccessContext, suggestion_id: UUID, *, today: date) -> UUID:
    """The person confirms the marking: it becomes the network's source profile, in the same transaction."""
    with deciding(ctx, suggestion_id, today=today) as (session, row):
        if row.kind != "mapping":
            raise InvalidError("Это не разметка файла")
        if row.status != "proposed":
            raise ConflictError("Эта разметка уже подтверждена или отклонена")
        content = row.content
        profile = imports.save_profile(
            session,
            ctx,
            template=content["template"],
            title=f"Профиль файла «{content['filename']}»",
            mapping={c["field"]: c["header"] for c in content["columns"]},
        )
        row.status, row.decision_note = "accepted", "разметка подтверждена"
        return profile.id
