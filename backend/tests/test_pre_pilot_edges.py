"""Edge cases of the fixes of the code review before the pilot (docs/reviews/2026-11-10-pre-pilot-review.md),
added by the test engineer after the review: what the first tests did not reach.

TC-IMP-26, 28, 29, 33, 36, 37, TC-AUTH-11, 12, TC-AI-39, 40.
"""

import io
import json
import re
import time
import zipfile
from collections import deque
from collections.abc import Iterator, MutableMapping
from datetime import date, timedelta
from typing import Any

import anyio
import pytest
import xlsxwriter
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.ai.gateway import FakeModel, Gateway, ModelRequest, Reply, get_gateway, text_reply
from app.ai.mapping import MASK, masked_samples
from app.catalog.models import Product, Supplier
from app.core import limits
from app.core.errors import InvalidError
from app.core.period import get_today
from app.imports import reader
from app.imports.reader import check_xlsx_size, read_rows
from app.imports.validate import _outlying_days
from app.main import app
from app.tenancy.models import Restaurant
from tests.conftest import PASSWORD, Network, login
from tests.test_imports_api import publish, upload

TODAY = date(2026, 10, 25)
PRODUCTS = "Код;Наименование;Категория;Базовая ед.\nP1;Сыр Моцарелла;Сыры;кг\nP2;Сливки 33%;Молочные;л\n"
MENU = "Код;Блюдо;Категория;Цена\nM1;Маргарита;Пицца;580\n"


@pytest.fixture(autouse=True)
def _pin_today() -> Iterator[None]:
    app.dependency_overrides[get_today] = lambda: TODAY
    yield
    app.dependency_overrides.pop(get_today, None)


@pytest.fixture
def hq(client: TestClient, network: Network) -> dict[str, str]:
    auth = login(client, "admin@a.ru")
    for template, content in (("products", PRODUCTS), ("menu_items", MENU)):
        publish(client, auth, upload(client, auth, template, content).json()["id"])
    return auth


# ------------------------------------------------------------------ far days (TC-IMP-29)

D = date(2026, 10, 1)


def test_far_days_ties_and_weights_are_decided_the_same_way_every_time() -> None:
    """TC-IMP-29: two groups of days, the bigger by rows is the file; with a tie the later one is."""
    june, october = [date(2026, 6, 1), date(2026, 6, 2)], [D, D + timedelta(days=1)]
    # 2 rows vs 2 rows: a tie, the later group (October) is the file, June is the typo
    assert _outlying_days("sales", june + october) == set(june)
    assert _outlying_days("sales", october + june) == set(june)  # the order of rows does not matter
    # one day of 5 rows (5) outweighs three days of one row each (3): it is March that is far
    january = [date(2026, 1, 15)] * 5
    march = [date(2026, 3, 1), date(2026, 3, 2), date(2026, 3, 3)]
    assert _outlying_days("sales", january + march) == set(march)


def test_far_days_the_gap_is_counted_between_neighbours_and_the_limit_is_inclusive() -> None:
    """TC-IMP-29: 31 days apart is one period, 32 — two; counts: 120 and 121; a chain of close days is one."""
    assert _outlying_days("sales", [D, D + timedelta(days=31)]) == set()
    # 32 days: two groups of one row each, the later one wins the tie → 01.10 is far
    assert _outlying_days("sales", [D, D + timedelta(days=32)]) == {D}
    assert _outlying_days("inventory_counts", [D, D + timedelta(days=120)]) == set()
    assert _outlying_days("inventory_counts", [D, D, D + timedelta(days=121)]) == {D + timedelta(days=121)}
    chain = [D + timedelta(days=20 * i) for i in range(6)]  # 100 days, never more than 20 between two
    assert _outlying_days("sales", chain) == set()
    assert _outlying_days("sales", []) == set()


def test_a_far_day_is_found_among_rows_that_wait_for_a_name(
    client: TestClient, hq: dict[str, str], network: Network
) -> None:
    """TC-IMP-36: rows waiting for name matching are days of the file too. A typo in the year — in a matched
    row among waiting ones, or in a waiting row — is an error at once, not after the person matched names
    (the period of the file would span 10 years meanwhile)."""
    waiting = "\n".join(f"{d:02d}.10.2026;Пицца Неизвестная;1;500" for d in range(1, 20))
    content = f"Дата;Блюдо;Кол-во;Сумма\n{waiting}\n01.10.2016;Маргарита;1;580\n"
    body = upload(client, hq, "sales", content, network.a.restaurants["A1"]).json()
    assert body["status"] == "failed", body
    assert [e["row"] for e in body["errors"]] == [21] and "проверьте год" in body["errors"][0]["message"]

    matched = "\n".join(f"{d:02d}.10.2026;Маргарита;1;580" for d in range(1, 20))
    content = f"Дата;Блюдо;Кол-во;Сумма\n{matched}\n01.10.2016;Пицца Неизвестная;1;500\n"
    body = upload(client, hq, "sales", content, network.a.restaurants["A1"]).json()
    assert body["status"] == "failed", body
    assert [e["row"] for e in body["errors"]] == [21] and "проверьте год" in body["errors"][0]["message"]


def test_a_date_before_2000_is_an_error_even_alone(
    client: TestClient, hq: dict[str, str], network: Network
) -> None:
    """TC-IMP-29: a file of one day in 1999 has no other days to be far from — still «проверьте год»."""
    content = "Дата;Блюдо;Кол-во;Сумма\n01.10.1999;Маргарита;1;580\n01.10.1999;Маргарита;2;1160\n"
    body = upload(client, hq, "sales", content, network.a.restaurants["A1"]).json()
    assert body["status"] == "failed"
    assert [e["row"] for e in body["errors"]] == [2, 3]
    assert all("проверьте год" in e["message"] for e in body["errors"])
    ok = "Дата;Блюдо;Кол-во;Сумма\n01.01.2000;Маргарита;1;580\n"  # the first day allowed
    assert upload(client, hq, "sales", ok, network.a.restaurants["A1"]).json()["status"] == "validated"


# ------------------------------------------------------------------ the size of a workbook (TC-IMP-26)


def _book(cells: dict[tuple[int, int], str]) -> bytes:
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True})
    ws = wb.add_worksheet()
    for (r, c), v in cells.items():
        ws.write(r, c, v)
    wb.close()
    return buf.getvalue()


BASE = _book({(0, 0): "Дата", (1, 0): "x"})
SHEET = "xl/worksheets/sheet1.xml"


def _with_sheet(rows_xml: bytes, base: bytes = BASE) -> bytes:
    """The workbook with its first sheet's <sheetData> replaced."""
    src = zipfile.ZipFile(io.BytesIO(base))
    xml = re.sub(rb"<sheetData>.*</sheetData>", b"<sheetData>" + rows_xml + b"</sheetData>", src.read(SHEET))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for info in src.infolist():
            z.writestr(info.filename, xml if info.filename == SHEET else src.read(info))
    return out.getvalue()


def _at_boundary(tag: bytes, before: int) -> bytes:
    """Rows of padding so that `tag` starts `before` bytes before the first 1 MB piece ends."""
    head = b'<row r="1"><c r="A1" t="inlineStr"><is><t>'
    tail = b"</t></is></c></row>"
    xml = zipfile.ZipFile(io.BytesIO(BASE)).read(SHEET)
    offset = xml.index(b"<sheetData>") + len(b"<sheetData>")
    pad = (1 << 20) - before - offset - len(head) - len(tail)
    return head + b"y" * pad + tail + b'<row r="5">' + tag + b"<v>1</v></c></row>"


def test_a_far_cell_whose_tag_is_cut_between_two_pieces_is_found() -> None:
    """TC-IMP-26: the XML is read by 1 MB; the far cell's tag starts in one piece and ends in the next."""
    raw = _with_sheet(_at_boundary(b'<c r="ALL5">', 5))
    with pytest.raises(InvalidError, match="слишком большая"):
        check_xlsx_size(raw)
    # a tag longer than the piece's overlap (attributes before r=) is found too
    long_tag = b'<c s="0" t="n" x14ac:dyDescent="' + b"0" * 1000 + b'" r="ALL5">'
    raw = _with_sheet(_at_boundary(long_tag, 600))
    with pytest.raises(InvalidError, match="слишком большая"):
        check_xlsx_size(raw)
    # a «>» inside an attribute does not hide the r= after it
    raw = _with_sheet(b'<row r="1"><c x="a>b" r="ALL1"><v>1</v></c></row>')
    with pytest.raises(InvalidError, match="слишком большая"):
        check_xlsx_size(raw)


def test_a_sheet_without_cell_addresses_is_measured_by_its_rows_and_cells(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TC-IMP-26: r= is optional in xlsx; without it every row and cell follows the previous one (calamine
    reads them so). Rows of one cell and one long row make a dense grid of rows × the longest row — at full
    scale 300 000 × 16 384 cells from 6 MB of XML — so the check counts them before fastexcel unpacks the
    sheet. The limits are lowered here to 50 rows and 20 columns."""
    monkeypatch.setattr(reader, "MAX_ROWS", 50)
    monkeypatch.setattr(reader, "MAX_COLUMNS", 20)
    one = b"<row><c><v>1</v></c></row>"
    check_xlsx_size(_with_sheet(one * 50))  # 50 rows: at the limit
    assert read_rows(_with_sheet(one * 3), "ok.xlsx") == [["1"], ["1"], ["1"]]
    with pytest.raises(InvalidError, match="слишком большая"):
        check_xlsx_size(_with_sheet(one * 51))
    check_xlsx_size(_with_sheet(b"<row>" + b"<c><v>1</v></c>" * 20 + b"</row>"))  # 20 cells: at the limit
    with pytest.raises(InvalidError, match="слишком большая"):
        check_xlsx_size(_with_sheet(b"<row>" + b"<c><v>1</v></c>" * 21 + b"</row>"))
    # a cell without r= after one with it goes on from it: T1 is column 20, the next one is 21
    with pytest.raises(InvalidError, match="слишком большая"):
        check_xlsx_size(_with_sheet(b'<row r="1"><c r="T1"><v>1</v></c><c><v>2</v></c></row>'))
    # a row without r= after r="50" is the 51st
    with pytest.raises(InvalidError, match="слишком большая"):
        check_xlsx_size(_with_sheet(b'<row r="50"><c r="A50"><v>1</v></c></row>' + one))


def test_an_archive_unpacking_too_big_and_a_tag_without_end_are_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TC-IMP-26: the unpacked size of the archive is checked before reading a sheet (400 MB, lowered here to
    1 KB); a tag that never ends within 4 MB (lowered to 1 MB) is not a sheet; a CSV over the rows (lowered
    to 3) is refused too."""
    monkeypatch.setattr(reader, "MAX_UNPACKED", 1024)
    with pytest.raises(InvalidError, match="слишком большая"):
        check_xlsx_size(BASE)
    monkeypatch.undo()
    monkeypatch.setattr(reader, "MAX_TAG", 1 << 20)
    endless = b'<row r="1"><c r="A1" t="inlineStr"><is><t>' + b"y" * (3 << 20) + b"</t></is></c></row>"
    with pytest.raises(InvalidError, match="Не удалось прочитать Excel"):
        check_xlsx_size(_with_sheet(endless))
    monkeypatch.setattr(reader, "MAX_ROWS", 3)
    assert len(read_rows(b"a;b\n1;2\n3;4\n", "ok.csv")) == 3
    with pytest.raises(InvalidError, match="слишком большая"):
        read_rows(b"a;b\n1;2\n3;4\n5;6\n", "long.csv")


def test_the_limits_of_a_sheet_are_inclusive() -> None:
    """TC-IMP-26: column 200 (GR) and row 300 000 are allowed; 201 (GS) and 300 001 are not."""
    check_xlsx_size(_with_sheet(b'<row r="300000"><c r="GR300000"><v>1</v></c></row>'))
    with pytest.raises(InvalidError):
        check_xlsx_size(_with_sheet(b'<row r="1"><c r="GS1"><v>1</v></c></row>'))
    with pytest.raises(InvalidError):
        check_xlsx_size(_with_sheet(b'<row r="300001"><c r="A300001"><v>1</v></c></row>'))


def test_a_workbook_broken_inside_its_zip_is_said_in_russian_never_a_500() -> None:
    """TC-IMP-28: the archive opens, but a sheet's compressed data is damaged (a file cut or changed in
    transit) — zlib's error is not the person's."""
    raw = bytearray(BASE)
    info = zipfile.ZipFile(io.BytesIO(BASE)).getinfo(SHEET)
    start = info.header_offset + 30 + len(info.filename.encode()) + len(info.extra)
    for i in range(start, start + 12):
        raw[i] ^= 0xFF
    with pytest.raises(InvalidError, match="Не удалось прочитать Excel"):
        read_rows(bytes(raw), "broken.xlsx")


# ------------------------------------------------------------------ values the database holds (TC-IMP-30)


def test_reference_texts_are_checked_against_their_own_columns(
    client: TestClient, hq: dict[str, str]
) -> None:
    """TC-IMP-37: a restaurant's code is 50 characters in the database and its name 200 (not 100 and 300 as
    for products); a 1С name in «Синхронизация» is 300. Longer — an error of the row, not a 500 on publish."""
    content = f"Код;Название;Город\n{'R' * 51};Ресторан;Москва\nR2;{'Р' * 201};Москва\nR3;Ресторан;Казань\n"
    body = upload(client, hq, "restaurants", content).json()
    assert body["status"] == "failed", body
    assert sorted(e["row"] for e in body["errors"]) == [2, 3]
    assert "до 50" in body["errors"][0]["message"] and "до 200" in body["errors"][1]["message"]

    content = f"Номенклатура ЕРП;Код iiko\n{'Сыр ' * 80};P1\nСыр моцарелла фасованный;P1\n"
    body = upload(client, hq, "name_sync", content).json()
    assert body["status"] == "failed", body
    assert [e["row"] for e in body["errors"]] == [2] and "до 300" in body["errors"][0]["message"]


# ------------------------------------------------------------------ partial reference files (TC-IMP-33)


def test_every_reference_template_keeps_the_columns_its_file_lacks(
    client: TestClient, hq: dict[str, str], owner_engine: Engine
) -> None:
    """TC-IMP-33: restaurants without «Город», suppliers without «ИНН», products without «Срок годности» and
    «Тип» — what the file does not say stays; what it says is updated."""
    full = (
        ("restaurants", "Код;Название;Город\nA1;Ресторан на Тверской;Москва\n"),
        ("suppliers", "Код;Название;ИНН\nS1;ООО Ромашка;7701000001\n"),
        (
            "products",
            "Код;Наименование;Категория;Базовая ед.;Срок годности, дней;Тип\n"
            "P3;Соус томатный;Соусы;кг;3;п/ф\n",
        ),
    )
    partial = (
        ("restaurants", "Код;Название\nA1;Тверская, 7\n"),
        ("suppliers", "Код;Название\nS1;ООО «Ромашка»\n"),
        ("products", "Код;Наименование;Базовая ед.\nP3;Соус томатный базовый;кг\n"),
    )
    for template, content in (*full, *partial):
        body = upload(client, hq, template, content).json()
        assert body["status"] == "validated", (template, body["errors"])
        publish(client, hq, body["id"])
    with Session(owner_engine) as s:
        tenant = network_tenant(s, "A1")
        r = s.execute(
            select(Restaurant).where(Restaurant.code == "A1", Restaurant.tenant_id == tenant)
        ).scalar_one()
        sup = s.execute(select(Supplier).where(Supplier.code == "S1")).scalar_one()
        p = s.execute(select(Product).where(Product.code == "P3")).scalar_one()
        assert (r.name, r.city) == ("Тверская, 7", "Москва")
        assert (sup.name, sup.inn) == ("ООО «Ромашка»", "7701000001")
        assert (p.name, p.category, p.shelf_life_days, p.is_semi) == (
            "Соус томатный базовый",
            "Соусы",
            3,
            True,
        )


def network_tenant(s: Session, code: str) -> Any:
    return s.execute(select(Restaurant.tenant_id).where(Restaurant.code == code)).scalars().first()


# ------------------------------------------------------------------ the body limit (TC-AUTH-11)


def _call(
    asgi: Any, path: str, chunks: list[bytes], headers: list[tuple[bytes, bytes]]
) -> list[dict[str, Any]]:
    """Runs BodyLimit around `asgi` on one request and returns what it sent."""
    sent: list[dict[str, Any]] = []
    messages = [
        {"type": "http.request", "body": c, "more_body": i < len(chunks) - 1} for i, c in enumerate(chunks)
    ]

    async def receive() -> dict[str, Any]:
        return messages.pop(0) if messages else {"type": "http.disconnect"}

    async def send(message: MutableMapping[str, Any]) -> None:
        sent.append(dict(message))

    scope: dict[str, Any] = {"type": "http", "path": path, "headers": headers}
    limit = limits.BodyLimit(asgi)
    anyio.run(lambda: limit(scope, receive, send))
    return sent


async def _ok(send: Any, status: int = 200) -> None:
    await send({"type": "http.response.start", "status": status, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


def _statuses(sent: list[dict[str, Any]]) -> list[int]:
    return [m["status"] for m in sent if m["type"] == "http.response.start"]


def test_the_body_limit_when_the_app_never_reads_the_body() -> None:
    """TC-AUTH-11: an endpoint that does not read the body answers as usual — nothing is read, nothing is
    spooled, whatever comes after; only a Content-Length over the limit (or not a number) is refused at
    once."""
    read: list[int] = []

    async def ignores(scope: Any, receive: Any, send: Any) -> None:
        read.append(0)
        await _ok(send)

    big = [b" " * 65_536] * (limits.BODY_LIMIT // 65_536 + 2)
    assert _statuses(_call(ignores, "/api/auth/me", big, [])) == [200]
    assert _statuses(_call(ignores, "/api/auth/me", [b"{}"], [(b"content-length", b"abc")])) == [413]
    assert _statuses(_call(ignores, "/api/auth/me", [b"{}"], [(b"content-length", b"-1")])) == [413]
    over = str(limits.BODY_LIMIT + 1).encode()
    assert _statuses(_call(ignores, "/api/auth/me", [b"{}"], [(b"content-length", over)])) == [413]
    assert len(read) == 1  # refused by the header: the app was never called
    # the limit itself is allowed; the upload paths (the assistant's marking too) take files up to 21 MB
    at = str(limits.BODY_LIMIT).encode()
    assert _statuses(_call(ignores, "/api/auth/me", [b"{}"], [(b"content-length", at)])) == [200]
    big_file = str(limits.UPLOAD_LIMIT).encode()
    for path in ("/api/imports", "/api/imports/mapping", "/api/imports/abc/match"):
        assert _statuses(_call(ignores, path, [b""], [(b"content-length", big_file)])) == [200], path
    too_big = str(limits.UPLOAD_LIMIT + 1).encode()
    assert _statuses(_call(ignores, "/api/imports", [b""], [(b"content-length", too_big)])) == [413]


def test_the_body_limit_answers_once_whatever_the_app_made_of_a_cut_body() -> None:
    """TC-AUTH-11: the app read past the limit and answered 200 or 500 — the visitor hears one 413."""

    async def reads_all(scope: Any, receive: Any, send: Any) -> None:
        while (await receive())["type"] == "http.request":
            pass
        assert (await receive())["type"] == "http.disconnect"  # asked again: still gone, nothing more read
        await _ok(send, 500)
        await _ok(send, 200)

    big = [b" " * 65_536] * (limits.BODY_LIMIT // 65_536 + 2)
    sent = _call(reads_all, "/api/tasks", big, [])
    assert _statuses(sent) == [413]
    assert sum(1 for m in sent if m["type"] == "http.response.body") == 1
    small = _call(reads_all, "/api/tasks", [b"{}", b"{}"], [])
    assert _statuses(small) == [500, 200]  # under the limit the app's own answers pass

    async def lifespan(scope: Any, receive: Any, send: Any) -> None:
        await send({"type": "lifespan.startup.complete"})

    out: list[Any] = []

    async def collect(m: Any) -> None:
        out.append(m)

    async def nothing() -> Any:
        return {}

    passing = limits.BodyLimit(lifespan)
    anyio.run(lambda: passing({"type": "lifespan"}, nothing, collect))
    assert out == [{"type": "lifespan.startup.complete"}]


def test_an_upload_streamed_without_a_length_is_refused_without_a_token(client: TestClient) -> None:
    """TC-AUTH-11: a «file» of 22 MB sent in chunks with no Content-Length and no token — 413, not 401 after
    spooling it."""

    def chunks() -> Iterator[bytes]:
        for _ in range(limits.UPLOAD_LIMIT // (1 << 20) + 2):
            yield b"x" * (1 << 20)

    r = client.post(
        "/api/imports", content=chunks(), headers={"Content-Type": "multipart/form-data; boundary=xyz"}
    )
    assert r.status_code == 413 and "20 МБ" in r.json()["detail"]


# ------------------------------------------------------------------ signing in (TC-AUTH-12)


def _try_login(client: TestClient, email: str, password: str, ip: str) -> int:
    r = client.post(
        "/api/auth/login", json={"email": email, "password": password}, headers={"X-Forwarded-For": ip}
    )
    return r.status_code


def test_failed_sign_ins_are_counted_per_address_across_emails(client: TestClient, network: Network) -> None:
    """TC-AUTH-12: ten wrong passwords for ten emails from one address (spraying one password) — the
    eleventh attempt from it waits, even for the right one; another address is not affected."""
    for i in range(limits.MAX_FAILURES):
        assert _try_login(client, f"nobody{i}@a.ru", "wrong-pass", "10.0.0.7") == 401
    assert _try_login(client, "director1@a.ru", PASSWORD, "10.0.0.7") == 429
    assert _try_login(client, "director1@a.ru", PASSWORD, "10.0.0.8") == 200


def test_a_successful_sign_in_does_not_forgive_the_address(client: TestClient, network: Network) -> None:
    """TC-AUTH-12: a person with an account cannot reset the counter of their address by signing in between
    guesses: success forgets only that email's failures. 9 failures + 1 success + 1 failure = 10 → 429."""
    ip = "10.0.0.9"
    for i in range(limits.MAX_FAILURES - 1):
        assert _try_login(client, f"victim{i}@a.ru", "wrong-pass", ip) == 401
    assert _try_login(client, "director1@a.ru", PASSWORD, ip) == 200
    assert _try_login(client, "victim9@a.ru", "wrong-pass", ip) == 401
    assert _try_login(client, "director2@a.ru", PASSWORD, ip) == 429


def test_the_email_key_ignores_case_and_the_window_ends(client: TestClient, network: Network) -> None:
    """TC-AUTH-12: «ADMIN@A.RU» is the same email as «admin@a.ru»; after 15 minutes the failures are gone."""
    for i in range(limits.MAX_FAILURES):
        email = "ADMIN@A.RU" if i % 2 else "admin@a.ru"
        assert _try_login(client, email, "wrong-pass", f"10.1.0.{i}") == 401
    assert _try_login(client, "admin@a.ru", PASSWORD, "10.2.0.1") == 429
    for times in limits.login_guard._failures.values():  # 15 minutes and a second pass
        for i in range(len(times)):
            times[i] -= limits.WINDOW_SECONDS + 1
    assert _try_login(client, "admin@a.ru", PASSWORD, "10.2.0.1") == 200


def test_the_table_of_failures_forgets_old_keys() -> None:
    """TC-AUTH-12: over 100 000 keys, those older than the window go (the table never grows without end)."""
    guard = limits.LoginGuard()
    old = time.monotonic() - limits.WINDOW_SECONDS - 5
    for i in range(100_001):
        guard._failures[f"ip:{i}"] = deque([old])
    guard.failed("ip:new")
    assert list(guard._failures) == ["ip:new"]


# ------------------------------------------------------------------ the model never sees people (TC-AI-39)


def test_masked_samples_cover_the_forms_of_a_name_and_keep_dishes() -> None:
    """TC-AI-39: a name in any column — «Иванов И.И.», «Иванов И. И.», «И.И. Иванов», a double surname, three
    words; columns of people by header (Ф.И.О., «Кто принял», «Ответственный»); dishes stay."""
    header = ["Блюдо", "Комментарий", "Ф.И.О.", "Кто принял", "Ответственный", "Сумма"]
    rows = [
        ["Пицца Маргарита", "Иванов И.И.", "таб. 7", "Сидоров", "", "580"],
        ["Салат Цезарь с курицей", "Иванов И. И.", "Петров", "", "Кузнецова", "1 200"],
        ["Паста Карбонара", "И.И. Иванов", "", "", "", "450"],
        ["Суп дня", "Петрова-Водкина Анна Сергеевна", "", "", "", "300"],
    ]
    assert masked_samples(header, rows) == [
        ["Пицца Маргарита", MASK, MASK, MASK, "", "580"],
        ["Салат Цезарь с курицей", MASK, MASK, "", MASK, "1 200"],
        ["Паста Карбонара", MASK, "", "", "", "450"],
        ["Суп дня", MASK, "", "", "", "300"],
    ]
    # a row longer than the header and an empty header are fine
    assert masked_samples(["Кассир"], [["Иванов", "Иванов И.И.", "x"]]) == [[MASK, MASK, "x"]]


@pytest.fixture
def model() -> Iterator[FakeModel]:
    fake = FakeModel()
    app.dependency_overrides[get_gateway] = lambda: Gateway(fake)
    yield fake
    app.dependency_overrides.pop(get_gateway, None)


def _marking(*pairs: tuple[str, str]) -> Any:
    def reply(_: ModelRequest) -> Reply:
        cols = [{"field": f, "header": h, "why": "по образцам"} for f, h in pairs]
        return text_reply(json.dumps({"columns": cols}, ensure_ascii=False))

    return reply


def test_the_errors_sent_back_to_the_model_carry_no_names(
    client: TestClient, network: Network, model: FakeModel
) -> None:
    """TC-AI-40: a marking that breaks the rows goes back to the model with the first errors of the import;
    those quote the cells («Петров П.П.» — ИНН …). A person's column or a name in them is masked as in the
    samples — the model never sees an employee, not in the second message either."""
    content = (
        "Справочник контрагентов\n\nИдентификатор;Юрлицо;Налоговый номер;Ответственный\n"
        "S1;ООО Ромашка;7701000001;Петров П.П.\nS2;ИП Лютиков;7701000002;Сидорова\n"
        "S3;ООО Мясо;7701000003;Кузнецов Иван Петрович\n"
    )
    model.replies += [
        _marking(("code", "Идентификатор"), ("name", "Юрлицо"), ("inn", "Ответственный")),
        _marking(("code", "Идентификатор"), ("name", "Юрлицо"), ("inn", "Налоговый номер")),
    ]
    admin = login(client, "admin@a.ru")
    r = client.post(
        "/api/imports/mapping",
        headers=admin,
        data={"template": "suppliers"},
        files={"file": ("контрагенты.csv", content.encode(), "text/csv")},
    )
    assert r.status_code == 200, r.text
    assert len(model.requests) == 2
    second = json.dumps([m for m in model.requests[1].messages], ensure_ascii=False)
    assert "ИНН" in second  # the error did go back
    for name in ("Петров", "Сидорова", "Кузнецов"):
        assert all(name not in json.dumps(q.messages, ensure_ascii=False) for q in model.requests), name


def test_a_number_that_rounds_up_to_the_limit_is_an_error_of_its_row() -> None:
    """TC-IMP-30: 9 999 999 999,99995 is below 10¹⁰, but Numeric(14, 4) rounds it to 10¹⁰."""
    from decimal import Decimal

    from app.imports.templates import TEMPLATES
    from app.imports.validate import _fits, _RowError

    with pytest.raises(_RowError, match="слишком большое число"):
        _fits({"qty": Decimal("9999999999.99995")}, TEMPLATES["write_offs"])
    _fits({"qty": Decimal("9999999999.9999")}, TEMPLATES["write_offs"])
