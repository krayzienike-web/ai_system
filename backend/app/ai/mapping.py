"""An unfamiliar export (ADR 0008, stage 5.5; docs/09, «Адаптивный импорт»): the assistant marks which column
is which, the import checks the marking on the file itself, a person confirms it once and it becomes a source
profile — later files with these headers load by it through the whole validation.

Order: the header row is found by the code; the template's synonyms and the network's profiles map what they
can; only the rest goes to the model, with the headers and a few sample rows. A marking the import cannot read
(no header, a required column missing, most rows in error) goes back to the model once, then there is no
proposal.
"""

import hashlib
import re
from datetime import date
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.ai.gateway import Gateway
from app.ai.suggestions import Proposal, ask, deciding, keep
from app.core.errors import ForbiddenError, InvalidError
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


PERSON_HEADERS = re.compile(
    r"кассир|официант|сотрудник|бармен|менеджер|ответствен|исполнител|автор|кто |^кто$|фио|ф\.и\.о|"
    r"оператор|пользовател|работник|персонал|телефон|e-?mail|почта",
    re.IGNORECASE,
)
# «Иванов И.И.», «Иванов Иван Иванович», «И.И. Иванов»: a person's name in any column
_SURNAME = r"[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?"
PERSON_VALUE = re.compile(
    rf"^(?:{_SURNAME}\s+(?:[А-ЯЁ]\.\s?[А-ЯЁ]\.?|[А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+)|[А-ЯЁ]\.\s?[А-ЯЁ]\.\s?{_SURNAME})$"
)
MASK = "[сотрудник]"
QUOTED = re.compile(r"«([^»]*)»")


def _private(header: list[str]) -> set[int]:
    return {i for i, h in enumerate(header) if PERSON_HEADERS.search(h.strip())}


def masked_samples(header: list[str], rows: list[list[str]]) -> list[list[str]]:
    """The sample rows the model sees, without people: the columns of cashiers and waiters and anything that
    looks like a full name are replaced (docs/03: no personal data to the LLM; pre-pilot review, p. 12)."""
    private = _private(header)
    return [
        [
            MASK if (i in private and c.strip()) or PERSON_VALUE.match(c.strip()) else c.strip()
            for i, c in enumerate(r)
        ]
        for r in rows
    ]


def masked_text(text: str, header: list[str], rows: list[list[str]]) -> str:
    """A message of the import that goes back to the model: a quoted cell of a person's column or a name is
    masked as in the samples (the import's errors quote cells: «Петров П.П.» — ИНН …)."""
    private = _private(header)
    people = {c.strip() for r in rows for i, c in enumerate(r) if i in private and c.strip()}

    def mask(m: re.Match[str]) -> str:
        value = m.group(1).strip()
        return f"«{MASK}»" if value in people or PERSON_VALUE.match(value) else m.group(0)

    return QUOTED.sub(mask, text)


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


MAX_BYTES = 20 * 1024 * 1024


def allowed(ctx: AccessContext, template_name: str, restaurant_id: UUID | None) -> Template:
    """Who may mark this file: whoever may upload it (code review 02.11.2026, p. 10) — checked before the
    model is even asked."""
    if not ctx.can(Permission.DATA_UPLOAD):
        raise ForbiddenError("Размечать файлы может тот, кто загружает данные")
    t = TEMPLATES.get(template_name)
    if t is None:
        raise InvalidError(f"Неизвестный шаблон: {template_name}")
    with user_session(ctx) as session:
        imports.check_access(session, ctx, t, restaurant_id)
    return t


def file_subject(template: str, raw: bytes, restaurant_id: UUID | None) -> UUID:
    """The subject of a marking: this file for this restaurant. A new marking replaces only an undecided
    marking of the same file, not another person's of another file (code review 02.11.2026, p. 7)."""
    digest = hashlib.sha256(raw).hexdigest()
    return uuid5(NAMESPACE_URL, f"souschef:mapping:{template}:{restaurant_id}:{digest}")


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
    if len(raw) > MAX_BYTES:
        raise InvalidError("Файл больше 20 МБ — разбейте выгрузку на несколько периодов")
    t = allowed(ctx, template_name, restaurant_id)
    rows = read_rows(raw, filename)
    index = guess_header(rows)
    headers = [c.strip() for c in rows[index] if c.strip()]
    with user_session(ctx) as session:
        aliases = imports.profile_aliases(session, restaurant_id).get(t.name, {})
        known, _ = map_header(rows[index], t, aliases)
    already = {name: rows[index][i].strip() for name, i in known.items()}
    basis = {
        "template": t.title,
        "fields": _fields(t),
        "headers": headers,
        "samples": masked_samples(rows[index], rows[index + 1 : index + 1 + SAMPLE_ROWS]),
        "already_mapped": already,
    }
    preview: dict[str, Any] = {}

    def check(m: Marking) -> list[str]:
        names = {c.name for c in t.columns}
        problems = [f"нет колонки шаблона {c.field}" for c in m.columns if c.field not in names]
        problems += [f"нет заголовка «{c.header}» в файле" for c in m.columns if c.header not in headers]
        # What the dictionary mapped stays: the model marks only the rest (code review 02.11.2026, p. 4).
        problems += [f"колонка {c.field} уже сопоставлена словарем" for c in m.columns if c.field in already]
        problems += [
            f"заголовок «{c.header}» уже сопоставлен словарем"
            for c in m.columns
            if c.header in already.values()
        ]
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
                return [masked_text(str(e), rows[index], rows[index + 1 :])]
        if tried["rows"] and tried["rows_with_errors"] / tried["rows"] > MOSTLY_BROKEN:
            bad, total = tried["rows_with_errors"], tried["rows"]
            errors = masked_text("; ".join(tried["errors"]), rows[index], rows[index + 1 :])
            return [f"с такой разметкой ошибки в {bad} строках из {total}: {errors}"]
        preview.clear()
        preview.update(tried)
        return []

    result, chat = ask(
        gateway, ctx, task="mapping", prompt_name="mapping", basis=basis, answer=Marking, check=check
    )
    columns = [{"field": f, "header": h, "why": "по словарю синонимов"} for f, h in already.items()]
    columns += [c.model_dump() for c in result.columns]  # exactly the marking the import read above
    content = {"template": t.name, "filename": filename[:300], "columns": columns, "preview": preview}
    (kept,) = keep(
        ctx,
        kind="mapping",
        subject_id=file_subject(t.name, raw, restaurant_id),
        restaurant_id=restaurant_id,
        contents=[content],
        basis=basis,
        chat=chat,
    )
    return kept, preview


def confirm(ctx: AccessContext, suggestion_id: UUID, *, today: date) -> UUID:
    """The person confirms the marking: it becomes a source profile in the same transaction — for the network
    when the HQ confirms, for the file's restaurant when a director does (imports.save_profile)."""
    with deciding(ctx, suggestion_id, today=today) as (session, row):
        if row.kind != "mapping":
            raise InvalidError("Это не разметка файла")
        content = row.content
        profile = imports.save_profile(
            session,
            ctx,
            template=content["template"],
            title=f"Профиль файла «{content['filename']}»",
            mapping={c["field"]: c["header"] for c in content["columns"]},
            restaurant_id=row.restaurant_id,
        )
        row.status, row.decision_note = "accepted", "разметка подтверждена"
        return profile.id
