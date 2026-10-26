"""Reading a CSV or XLSX file into rows of strings, finding the header and mapping columns.

Real exports often come "pretty": a title, empty rows, totals. The header is the first row that
names every required column; rows of totals are skipped (docs/09-data-requirements.md).
"""

import csv
import io
import re
from dataclasses import dataclass, field

import fastexcel

from app.core.errors import InvalidError
from app.imports.templates import Template

HEADER_SEARCH_ROWS = 30
TOTALS = re.compile(r"^\s*(итого|всего|total)\b", re.IGNORECASE)


@dataclass
class Table:
    header_row: int  # 1-based, as the user sees it in the file
    column_map: dict[str, int]  # canonical column -> index in the row
    unmapped: list[str]
    rows: list[tuple[int, list[str]]] = field(default_factory=list)  # (1-based file row, cells)
    skipped_totals: int = 0


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip().strip(":").lower()


def read_rows(content: bytes, filename: str) -> list[list[str]]:
    if filename.lower().endswith((".xlsx", ".xls")):
        try:
            sheet = fastexcel.read_excel(content).load_sheet(0, header_row=None, dtypes="string")
        except Exception as e:  # the file is not a readable workbook
            raise InvalidError(f"Не удалось прочитать Excel-файл: {e}") from None
        return [["" if v is None else str(v) for v in row] for row in sheet.to_polars().rows()]
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise InvalidError("Не удалось определить кодировку файла (ожидается UTF-8 или Windows-1251)")
    sample = text[:4096]
    delimiter = max((";", ",", "\t", "|"), key=sample.count)
    return [row for row in csv.reader(io.StringIO(text), delimiter=delimiter)]


def map_header(cells: list[str], template: Template) -> tuple[dict[str, int], list[str]]:
    found: dict[str, int] = {}
    unmapped = []
    for i, cell in enumerate(cells):
        name = _norm(cell)
        if not name:
            continue
        column = next((c for c in template.columns if name in c.synonyms or name == c.name), None)
        if column and column.name not in found:
            found[column.name] = i
        else:
            unmapped.append(cell.strip())
    return found, unmapped


def _complete(found: dict[str, int], template: Template) -> bool:
    required = all(c.name in found for c in template.columns if c.required)
    return required and all(any(n in found for n in group) for group in template.one_of)


def read_table(
    content: bytes, filename: str, template: Template, rows: list[list[str]] | None = None
) -> Table:
    rows = read_rows(content, filename) if rows is None else rows
    best: tuple[int, dict[str, int], list[str]] | None = None
    for i, cells in enumerate(rows[:HEADER_SEARCH_ROWS]):
        found, unmapped = map_header(cells, template)
        if _complete(found, template):
            best = (i, found, unmapped)
            break
    if best is None:
        required = [c.title for c in template.columns if c.required]
        groups = [" или ".join(template.column(n).title for n in g) for g in template.one_of]
        raise InvalidError("Не нашли строку заголовков. Нужны колонки: " + ", ".join(required + groups))
    index, found, unmapped = best
    table = Table(header_row=index + 1, column_map=found, unmapped=unmapped)
    for number, cells in enumerate(rows[index + 1 :], start=index + 2):
        if not any(c.strip() for c in cells):
            continue
        if TOTALS.match(next((c for c in cells if c.strip()), "")):
            table.skipped_totals += 1
            continue
        table.rows.append((number, cells))
    return table


def detect_template(content: bytes, filename: str, candidates: list[Template]) -> Template:
    """What is this file? The template whose header fits best: all its required columns are present,
    and among those the one that recognises the most columns. The user does not have to say it."""
    rows = read_rows(content, filename)
    best: tuple[int, Template] | None = None
    for template in candidates:
        try:
            table = read_table(content, filename, template, rows)
        except InvalidError:
            continue
        score = len(table.column_map)
        if best is None or score > best[0]:
            best = (score, template)
    if best is None:
        titles = ", ".join(t.title.lower() for t in candidates)
        raise InvalidError(f"Не узнали файл. Ожидали один из: {titles}. Проверьте строку заголовков")
    return best[1]
