"""Reading a CSV or XLSX file into rows of strings, finding the header and mapping columns.

Real exports often come "pretty": a title, empty rows, totals. The header is the first row that
names every required column; rows of totals are skipped (docs/09-data-requirements.md).
"""

import csv
import io
import logging
import re
import zipfile
from dataclasses import dataclass, field

import fastexcel

from app.core.errors import InvalidError
from app.imports.templates import Template

HEADER_SEARCH_ROWS = 30
TOTALS = re.compile(r"^\s*(итого|всего|total)\b", re.IGNORECASE)
# The sheet as calamine holds it is a dense grid: a 5 KB file with a cell at ALL10000 is 10 million cells
# (pre-pilot review 10.11.2026, p. 2). Real exports stay far below these limits.
MAX_ROWS = 300_000
MAX_COLUMNS = 200
MAX_UNPACKED = 400 * 1024 * 1024  # all the XML of a workbook, unpacked
TOO_BIG = (
    f"Таблица слишком большая: до {MAX_ROWS:,} строк и {MAX_COLUMNS} колонок на листе. "
    "Разбейте выгрузку на несколько периодов"
).replace(",", " ")
NOT_A_TABLE = "Не удалось прочитать Excel-файл: сохраните его в Excel как .xlsx или как CSV и загрузите снова"
log = logging.getLogger(__name__)
_CELL = re.compile(rb'<(?:\w+:)?c\b[^>]*?\br="([A-Z]{1,4})(\d{1,9})"')
_ROW = re.compile(rb'<(?:\w+:)?row\b[^>]*?\br="(\d{1,9})"')


@dataclass
class Table:
    header_row: int  # 1-based, as the user sees it in the file
    column_map: dict[str, int]  # canonical column -> index in the row
    unmapped: list[str]
    rows: list[tuple[int, list[str]]] = field(default_factory=list)  # (1-based file row, cells)
    skipped_totals: int = 0


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip().strip(":").lower()


def _column_number(letters: bytes) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ch - 64
    return n


def check_xlsx_size(content: bytes) -> None:
    """The size of every sheet of an .xlsx before it is unpacked into memory: its XML is read in pieces and
    the farthest cell is found. Raises InvalidError for a sheet over the limits or a zip unpacking too big."""
    try:
        book = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise InvalidError(NOT_A_TABLE) from None
    with book:
        sheets = [
            i
            for i in book.infolist()
            if i.filename.startswith("xl/worksheets/") and i.filename.endswith(".xml")
        ]
        if sum(i.file_size for i in book.infolist()) > MAX_UNPACKED:
            raise InvalidError(TOO_BIG)
        for info in sheets:
            rows = columns = 0
            tail = b""
            with book.open(info) as xml:
                while chunk := xml.read(1 << 20):
                    data = tail + chunk
                    rows = max([rows, *(int(m) for m in _ROW.findall(data))])
                    columns = max([columns, *(_column_number(c) for c, _ in _CELL.findall(data))])
                    rows = max([rows, *(int(r) for _, r in _CELL.findall(data))])
                    if rows > MAX_ROWS or columns > MAX_COLUMNS:
                        raise InvalidError(TOO_BIG)
                    tail = data[-256:]  # a tag cut between two pieces is read with the next one


def _decode(content: bytes) -> str:
    if content.startswith((b"\xff\xfe", b"\xfe\xff")):  # Excel «Юникод-текст» (p. 14)
        return content.decode("utf-16")
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise InvalidError("Не удалось определить кодировку файла (ожидается UTF-8 или Windows-1251)")


DELIMITERS = (";", "\t", ",", "|")


def _delimiter(text: str) -> str:
    """The separator that cuts the first lines into the same number of columns, more than one; a comma inside
    a dish name or a decimal comma does not win over «;» (p. 13). Ties go to the order of DELIMITERS."""
    lines = [line for line in text[:16384].splitlines() if line.strip()][:20]

    def score(d: str) -> tuple[int, int]:
        try:
            widths = [len(r) for r in csv.reader(lines, delimiter=d)]
        except csv.Error:
            return (0, 0)
        if not widths or max(widths) < 2:
            return (0, 0)
        common = max(set(widths), key=widths.count)
        return (widths.count(common) if common > 1 else 0, common)

    return max(DELIMITERS, key=score)


def read_rows(content: bytes, filename: str) -> list[list[str]]:
    if filename.lower().endswith((".xlsx", ".xls")):
        if content.startswith(b"PK"):
            check_xlsx_size(content)
        try:
            reader = fastexcel.read_excel(content)
            sheet = reader.load_sheet(0, header_row=None, dtypes="string", n_rows=MAX_ROWS + 1)
            if sheet.width > MAX_COLUMNS or sheet.total_height > MAX_ROWS:
                raise InvalidError(TOO_BIG)
            frame = sheet.to_polars()
        except InvalidError:
            raise
        except (
            Exception
        ):  # the file is not a readable workbook: the reason goes to the log, not to the person
            log.info("unreadable workbook %s", filename, exc_info=True)
            raise InvalidError(NOT_A_TABLE) from None
        return [["" if v is None else str(v) for v in row] for row in frame.rows()]
    text = _decode(content)
    try:
        rows = list(csv.reader(io.StringIO(text), delimiter=_delimiter(text)))
    except csv.Error:  # a field over csv's limit, a NUL byte: not a table we can read
        raise InvalidError(
            "Не удалось прочитать CSV: сохраните файл из Excel как CSV (разделитель «;»)"
        ) from None
    if len(rows) > MAX_ROWS:
        raise InvalidError(TOO_BIG)
    return rows


def norm_header(text: str) -> str:
    """A header as it is compared: spaces collapsed, case and a trailing colon dropped."""
    return _norm(text)


def map_header(
    cells: list[str], template: Template, aliases: dict[str, str] | None = None
) -> tuple[dict[str, int], list[str]]:
    """Columns by the template's synonyms and by the network's confirmed profiles (`aliases`: a normalized
    header → the template's column)."""
    found: dict[str, int] = {}
    unmapped = []
    for i, cell in enumerate(cells):
        name = _norm(cell)
        if not name:
            continue
        # The template's own words first: a profile adds headers, it never takes a synonym away
        # (code review 02.11.2026, p. 5: «Сумма» stays the amount whatever a profile says).
        column = next((c for c in template.columns if name in c.synonyms or name == c.name), None)
        if column is None and (alias := (aliases or {}).get(name)):
            column = next((c for c in template.columns if c.name == alias), None)
        if column and column.name not in found:
            found[column.name] = i
        else:
            unmapped.append(cell.strip())
    return found, unmapped


def _complete(found: dict[str, int], template: Template) -> bool:
    required = all(c.name in found for c in template.columns if c.required)
    return required and all(any(n in found for n in group) for group in template.one_of)


def read_table(
    content: bytes,
    filename: str,
    template: Template,
    rows: list[list[str]] | None = None,
    aliases: dict[str, str] | None = None,
) -> Table:
    rows = read_rows(content, filename) if rows is None else rows
    best: tuple[int, dict[str, int], list[str]] | None = None
    for i, cells in enumerate(rows[:HEADER_SEARCH_ROWS]):
        found, unmapped = map_header(cells, template, aliases)
        if _complete(found, template):
            best = (i, found, unmapped)
            break
    if best is None:
        required = [c.title for c in template.columns if c.required]
        groups = [" или ".join(template.column(n).title for n in g) for g in template.one_of]
        raise InvalidError(
            "Не нашли строку заголовков. Нужны колонки: " + ", ".join(required + groups), code="no_header"
        )
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


def detect_template(
    content: bytes,
    filename: str,
    candidates: list[Template],
    aliases: dict[str, dict[str, str]] | None = None,
) -> Template:
    """What is this file? The template whose header fits best: all its required columns are present,
    and among those the one that recognises the most columns. The user does not have to say it."""
    rows = read_rows(content, filename)
    best: tuple[int, Template] | None = None
    for template in candidates:
        try:
            table = read_table(content, filename, template, rows, (aliases or {}).get(template.name))
        except InvalidError:
            continue
        score = len(table.column_map)
        if best is None or score > best[0]:
            best = (score, template)
    if best is None:
        titles = ", ".join(t.title.lower() for t in candidates)
        raise InvalidError(
            f"Не узнали файл. Ожидали один из: {titles}. Проверьте строку заголовков", code="no_header"
        )
    return best[1]
