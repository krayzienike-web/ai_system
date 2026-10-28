"""The chat through the model (docs/08), on the scripted model: tools in a loop, every number checked,
conversations kept per person, the stream of statuses, the fallback to the answer by rules."""

import json
from collections.abc import Iterator
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.ai.chat import CORRECT
from app.ai.gateway import FakeModel, Gateway, ModelRequest, Reply, get_gateway, text_reply, tool_reply
from app.ai.verify import numbers, unsupported
from app.chat.assistant import CHECKED
from app.main import app
from tests.conftest import Network, login
from tests.test_overview import TODAY, demo  # noqa: F401  (the demo network: tenant A, director r01@a.ru)


@pytest.fixture
def model() -> Iterator[FakeModel]:
    fake = FakeModel()
    app.dependency_overrides[get_gateway] = lambda: Gateway(fake)
    yield fake
    app.dependency_overrides.pop(get_gateway, None)


def _tool_result(request: ModelRequest) -> dict[str, Any]:
    """The last tool result the model was given."""
    for message in reversed(request.messages):
        for block in message["content"] if isinstance(message["content"], list) else []:
            if block.get("type") == "tool_result":
                result: dict[str, Any] = json.loads(block["content"])
                return result
    raise AssertionError("no tool result in the request")


def test_numbers_are_compared_as_values() -> None:
    assert numbers("12 400 ₽, 31,2%, 0.5 и 1 250 000") == {
        Decimal("12400"),
        Decimal("31.2"),
        Decimal("0.5"),
        Decimal("1250000"),
    }
    assert numbers("с 20.10.2026") == {Decimal("20.1"), Decimal("2026")}
    source = {"food_cost": "31,2%", "loss": "12 400 ₽", "period": "01.09.2026–30.09.2026"}
    assert (
        unsupported("Фудкост 31.2 %, потери 12400 ₽ за 01.09.2026–30.09.2026, три шага: 1, 2, 3", [source])
        == []
    )
    assert unsupported("Потери 12 500 ₽, в год 148 800 ₽", [source]) == ["12500", "148800"]


def test_the_assistant_answers_from_tools_and_the_conversation_goes_on(
    client: TestClient,
    network: Network,
    demo: dict[str, UUID],  # noqa: F811
    model: FakeModel,
) -> None:
    director = login(client, "r01@a.ru")
    model.replies += [
        tool_reply("get_kpis", {}),
        lambda r: text_reply(f"Фудкост у вас {_tool_result(r)['restaurants'][0]['food_cost_actual']}."),
    ]
    first = client.post("/api/chat", headers=director, json={"question": "Какой у меня фудкост?"}).json()
    assert first["text"].startswith("Фудкост у вас ") and first["source"] == CHECKED
    assert first["thread_id"]
    # The tools offered to a director: no comparison of restaurants by name.
    names = [t["name"] for t in model.requests[0].tools]
    assert "get_kpis" in names and "compare_restaurants" not in names

    model.replies.append(text_reply("Да, это за период между инвентаризациями."))
    again = client.post(
        "/api/chat", headers=director, json={"question": "Это за месяц?", "thread_id": first["thread_id"]}
    ).json()
    assert again["thread_id"] == first["thread_id"]
    replayed = model.requests[-1].messages
    assert replayed[0]["content"][0]["text"] == "Какой у меня фудкост?"
    assert any(b.get("type") == "tool_use" for m in replayed for b in m["content"] if isinstance(b, dict))
    assert replayed[-1]["content"][0]["text"] == "Это за месяц?"

    threads = client.get("/api/chat/threads", headers=director).json()
    assert [t["title"] for t in threads] == ["Какой у меня фудкост?"]
    lines = client.get(f"/api/chat/threads/{first['thread_id']}", headers=director).json()
    assert [(line["role"], line["text"]) for line in lines] == [
        ("user", "Какой у меня фудкост?"),
        ("assistant", first["text"]),
        ("user", "Это за месяц?"),
        ("assistant", "Да, это за период между инвентаризациями."),
    ]


def test_a_conversation_is_its_authors_only(client: TestClient, network: Network, model: FakeModel) -> None:
    """TC-ISO: not another director of the network, not the HQ, not another network."""
    model.replies.append(text_reply("Ответ"))
    mine = client.post("/api/chat", headers=login(client, "director1@a.ru"), json={"question": "Мой вопрос"})
    thread = mine.json()["thread_id"]
    for email in ("director2@a.ru", "admin@a.ru", "admin@b.ru"):
        headers = login(client, email)
        assert client.get(f"/api/chat/threads/{thread}", headers=headers).status_code == 404
        assert client.get("/api/chat/threads", headers=headers).json() == []
        r = client.post("/api/chat", headers=headers, json={"question": "Продолжу", "thread_id": thread})
        assert r.status_code == 404


def test_a_number_not_in_the_data_is_corrected_once_then_the_answer_by_rules_is_shown(
    client: TestClient, network: Network, model: FakeModel
) -> None:
    headers = login(client, "director1@a.ru")
    model.replies += [text_reply("Вы теряете 48 000 ₽ в месяц."), text_reply("Данных о потерях пока нет.")]
    fixed = client.post("/api/chat", headers=headers, json={"question": "Сколько я теряю?"}).json()
    assert fixed["text"] == "Данных о потерях пока нет."
    correction = model.requests[1].messages[-1]["content"][0]["text"]
    assert correction == CORRECT.format(numbers="48000")

    model.replies += [text_reply("Вы теряете 48 000 ₽."), text_reply("Нет, 51 000 ₽.")]
    fallback = client.post("/api/chat", headers=headers, json={"question": "Как снизить списания?"}).json()
    assert fallback["source"] != CHECKED and "48" not in fallback["text"] and "51" not in fallback["text"]
    assert fallback[
        "thread_id"
    ]  # the attempt is kept in the conversation, the shown answer is the checked one


def test_refusals_long_answers_and_an_unreachable_model(
    client: TestClient, network: Network, model: FakeModel
) -> None:
    headers = login(client, "director1@a.ru")
    model.replies.append(Reply([], "refusal"))
    assert "не отвечу" in client.post("/api/chat", headers=headers, json={"question": "?"}).json()["text"]
    model.replies.append(Reply([{"type": "text", "text": "…"}], "max_tokens"))
    assert (
        "слишком длинным" in client.post("/api/chat", headers=headers, json={"question": "?"}).json()["text"]
    )
    # No reply scripted: the model is unavailable — the answer by rules, not an error.
    r = client.post("/api/chat", headers=headers, json={"question": "Где я переплачиваю?"})
    assert r.status_code == 200 and r.json()["source"] != CHECKED


def test_a_finding_of_another_restaurant_is_not_given_to_the_model_as_context(
    client: TestClient, network: Network, model: FakeModel, owner_engine: Any
) -> None:
    from sqlalchemy.orm import Session

    from app.insights.models import Finding

    with Session(owner_engine) as s, s.begin():
        other = Finding(
            tenant_id=network.a.id,
            restaurant_id=network.a.restaurants["A2"],
            kind="problem",
            process="production",
            title="Находка A2",
            effect_rub_month=Decimal("1000.00"),
            actions=["Шаг"],
            found_on=TODAY,
        )
        s.add(other)
        s.flush()
        other_id = other.id
    model.replies.append(text_reply("Ответ"))
    r = client.post(
        "/api/chat",
        headers=login(client, "director1@a.ru"),
        json={"question": "Почему?", "finding_id": str(other_id)},
    )
    assert r.status_code == 200
    assert str(other_id) not in json.dumps(model.requests[0].messages, ensure_ascii=False)


def test_the_stream_says_what_the_assistant_looks_at_then_answers(
    client: TestClient, network: Network, model: FakeModel
) -> None:
    model.replies += [tool_reply("get_findings", {}), text_reply("Открытых находок нет.")]
    with client.stream(
        "POST", "/api/chat/stream", headers=login(client, "director1@a.ru"), json={"question": "Что у меня?"}
    ) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        events = [
            (
                block.split("\n")[0].removeprefix("event: "),
                json.loads(block.split("\n")[1].removeprefix("data: ")),
            )
            for block in r.read().decode().strip().split("\n\n")
        ]
    assert events[0] == ("status", {"text": "Смотрю находки"})
    assert events[-1][0] == "answer" and events[-1][1]["text"] == "Открытых находок нет."


def test_the_budget_is_an_error_event_in_the_stream_and_429_otherwise(
    client: TestClient, network: Network
) -> None:
    app.dependency_overrides[get_gateway] = lambda: Gateway(FakeModel([text_reply("1")]), per_user_day=0)
    try:
        headers = login(client, "director1@a.ru")
        assert client.post("/api/chat", headers=headers, json={"question": "?"}).status_code == 429
        body = client.post("/api/chat/stream", headers=headers, json={"question": "?"}).text
        assert body.startswith("event: error") and '"status": 429' in body
    finally:
        app.dependency_overrides.pop(get_gateway, None)


def test_without_the_model_the_chat_answers_by_rules_and_keeps_no_conversation(
    client: TestClient, network: Network
) -> None:
    headers = login(client, "director1@a.ru")
    r = client.post("/api/chat", headers=headers, json={"question": "Где я переплачиваю?"}).json()
    assert r["thread_id"] is None and r["source"] != CHECKED
    assert client.get("/api/chat/threads", headers=headers).json() == []
