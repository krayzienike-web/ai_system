"""An unfamiliar export (ADR 0008, stage 5.5; docs/09, «Адаптивный импорт»): the assistant marks the columns,
the import checks the marking on the file, a person confirms it once, and later files load by the profile."""

import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.ai.gateway import FakeModel, Gateway, ModelRequest, Reply, get_gateway, text_reply
from app.ai.mapping import guess_header
from app.main import app
from tests.conftest import Network, login

STRANGE = (
    "Справочник контрагентов\n\nИдентификатор;Юрлицо;Налоговый номер\n"
    "S1;ООО Ромашка;7701000001\nS2;ИП Лютиков;7701000002\nS3;ООО Мясо;7701000003\n"
)
NEXT_MONTH = "Справочник контрагентов\n\nИдентификатор;Юрлицо;Налоговый номер\nS4;ООО Рыба;7701000004\n"


@pytest.fixture
def model() -> Iterator[FakeModel]:
    fake = FakeModel()
    app.dependency_overrides[get_gateway] = lambda: Gateway(fake)
    yield fake
    app.dependency_overrides.pop(get_gateway, None)


def marking(*pairs: tuple[str, str]) -> Any:
    def reply(_: ModelRequest) -> Reply:
        cols = [{"field": f, "header": h, "why": "по образцам"} for f, h in pairs]
        return text_reply(json.dumps({"columns": cols}, ensure_ascii=False))

    return reply


def _send(client: TestClient, headers: dict[str, str], path: str, content: str, template: str | None) -> Any:
    data = {"template": template} if template else {}
    return client.post(
        path, headers=headers, data=data, files={"file": ("контрагенты.csv", content.encode(), "text/csv")}
    )


def test_the_header_of_an_unknown_file_is_found_by_the_code() -> None:
    rows = [
        ["Справочник контрагентов"],
        [],
        ["Идентификатор", "Юрлицо", "Налоговый номер"],
        ["S1", "ООО", "77"],
    ]
    assert guess_header(rows) == 2


def test_marked_once_confirmed_once_then_files_load_by_the_profile(
    client: TestClient, network: Network, model: FakeModel
) -> None:
    admin = login(client, "admin@a.ru")
    first = _send(client, admin, "/api/imports", STRANGE, "suppliers").json()
    assert first["status"] == "failed" and "заголовков" in first["errors"][0]["message"]

    # A marking without a required column fails the import's check and goes back once; the second one reads.
    model.replies += [
        marking(("code", "Идентификатор")),
        marking(("code", "Идентификатор"), ("name", "Юрлицо"), ("inn", "Налоговый номер")),
    ]
    marked = _send(client, admin, "/api/imports/mapping", STRANGE, "suppliers").json()
    assert "Название" in model.requests[1].messages[-1]["content"][0]["text"]
    assert {c["field"]: c["header"] for c in marked["columns"]} == {
        "code": "Идентификатор",
        "name": "Юрлицо",
        "inn": "Налоговый номер",
    }
    assert marked["preview"]["rows"] == 3 and marked["preview"]["rows_with_errors"] == 0
    facts = json.loads(model.requests[0].messages[0]["content"][0]["text"].split("\n", 1)[1])
    assert facts["headers"] == ["Идентификатор", "Юрлицо", "Налоговый номер"] and len(facts["samples"]) == 3

    saved = client.post(f"/api/imports/mapping/{marked['id']}/confirm", headers=admin).json()
    profiles = client.get("/api/imports/profiles", headers=admin).json()
    assert [p["id"] for p in profiles] == [saved["profile_id"]] and profiles[0]["template"] == "suppliers"
    # Now the same file and the next month's load with no template and no model.
    assert _send(client, admin, "/api/imports", STRANGE, None).json()["status"] == "validated"
    assert _send(client, admin, "/api/imports", NEXT_MONTH, "suppliers").json()["status"] == "validated"
    assert len(model.requests) == 2
    # Confirmed once: a second confirmation of the same proposal is refused.
    assert client.post(f"/api/imports/mapping/{marked['id']}/confirm", headers=admin).status_code == 409


def test_a_marking_that_breaks_most_rows_is_no_proposal(
    client: TestClient, network: Network, model: FakeModel
) -> None:
    admin = login(client, "admin@a.ru")
    swapped = marking(("code", "Идентификатор"), ("name", "Юрлицо"), ("inn", "Нет такого"))
    model.replies += [swapped, swapped]
    assert _send(client, admin, "/api/imports/mapping", STRANGE, "suppliers").status_code == 502


def test_who_may_mark_and_confirm(client: TestClient, network: Network, model: FakeModel) -> None:
    """TC-ISO: the network's reference files are the HQ's; another network neither sees nor confirms."""
    director, admin, foreign = (
        login(client, "director1@a.ru"),
        login(client, "admin@a.ru"),
        login(client, "admin@b.ru"),
    )
    assert _send(client, director, "/api/imports/mapping", STRANGE, "suppliers").status_code == 403
    model.replies.append(marking(("code", "Идентификатор"), ("name", "Юрлицо")))
    marked = _send(client, admin, "/api/imports/mapping", STRANGE, "suppliers").json()
    assert client.post(f"/api/imports/mapping/{marked['id']}/confirm", headers=foreign).status_code == 404
    assert client.post(f"/api/imports/mapping/{marked['id']}/confirm", headers=director).status_code == 404
    assert client.get("/api/imports/profiles", headers=foreign).json() == []
