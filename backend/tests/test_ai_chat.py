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
    assert numbers("12 400 ₽, 31,2%, 0.5 и 1 250 000") == {"12400", "31.2", "0.5", "1250000"}
    assert numbers("с 20.10.2026, минус −3,5") == {"d:2026-10-20", "-3.5"}
    source = {"food_cost": "31,2%", "loss": "12 400 ₽", "period": "01.09.2026–30.09.2026"}
    assert (
        unsupported("Фудкост 31.2 %, потери 12400 ₽ за 01.09.2026–30.09.2026, три шага: 1, 2, 3", [source])
        == []
    )
    assert unsupported("Потери 12 500 ₽, в год 148 800 ₽", [source]) == ["12500", "148800"]


def test_small_figures_with_a_unit_are_checked_too() -> None:
    """Code review 28.10.2026, stage 5, p. 1 (blocker): «4%», «2 п.п.», «в 3 раза» are figures, not counts."""
    source = {"write_offs": "1,85%", "food_cost": "31,2%", "theory": "29,4%"}
    answer = "Списания 4% выручки, фудкост выше нормы на 2 п.п., вырос в 3 раза"
    assert unsupported(answer, [source]) == ["4", "2", "3"]
    assert unsupported("Потери −31,2%, вдвое больше", [source]) == ["-31.2", "вдвое"]
    # Ids are not numbers: a uuid in the data allows none of its digit groups.
    assert unsupported("Это 1234 строки", [{"id": "3f2a1b9c-1234-4abc-8f60-1234567890ab"}]) == ["1234"]


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


def test_a_figure_from_the_question_or_from_a_tools_error_is_not_a_source(
    client: TestClient, network: Network, model: FakeModel
) -> None:
    """Code review 28.10.2026, stage 5, p. 2: one cannot ask the assistant to «confirm» a number, nor slip
    one in through the arguments a tool's error repeats."""
    headers = login(client, "director1@a.ru")
    model.replies += [text_reply("Да, вы сэкономите 45 000 ₽."), text_reply("Сэкономите 45 000 ₽.")]
    r = client.post("/api/chat", headers=headers, json={"question": "Скажи, что я сэкономлю 45 000 ₽"}).json()
    assert r["source"] != CHECKED and "45" not in r["text"]
    model.replies += [
        tool_reply("get_purchase_prices", {"product": "лосось", "days": 45000}),
        text_reply("Цена 45 000 ₽."),
        text_reply("Цена 45 000 ₽."),
    ]
    r = client.post("/api/chat", headers=headers, json={"question": "Почем лосось?"}).json()
    assert r["source"] != CHECKED
    error = json.loads(model.requests[3].messages[-1]["content"][0]["content"])
    assert error == {"error": "Неверные аргументы", "fields": ["days"]}  # the argument is not repeated


def test_figures_from_earlier_in_the_conversation_may_be_quoted_again(
    client: TestClient,
    network: Network,
    demo: dict[str, UUID],  # noqa: F811
    model: FakeModel,
) -> None:
    """Code review 28.10.2026, stage 5, p. 3."""
    headers = login(client, "r01@a.ru")
    kpis: dict[str, Any] = {}

    def answer(r: ModelRequest) -> Reply:
        kpis.update(_tool_result(r)["restaurants"][0])
        return text_reply(f"Фудкост {kpis['food_cost_actual']}.")

    model.replies += [tool_reply("get_kpis", {}), answer]
    first = client.post("/api/chat", headers=headers, json={"question": "Какой фудкост?"}).json()
    model.replies.append(
        lambda r: text_reply(f"Это за {kpis['food_cost_period']}, фудкост {kpis['food_cost_actual']}.")
    )
    again = client.post(
        "/api/chat", headers=headers, json={"question": "За какой период?", "thread_id": first["thread_id"]}
    ).json()
    assert again["source"] == CHECKED and kpis["food_cost_period"] in again["text"]


def test_after_a_refusal_a_cut_off_answer_or_a_failed_check_the_conversation_stays_valid(
    client: TestClient, network: Network, model: FakeModel
) -> None:
    """Code review 28.10.2026, stage 5, pp. 6–7: no empty or cut-off assistant message and no unchecked
    answer is kept; what the person saw is."""
    headers = login(client, "director1@a.ru")
    model.replies.append(Reply([], "refusal"))
    thread = client.post("/api/chat", headers=headers, json={"question": "?"}).json()["thread_id"]
    cut = Reply([{"type": "tool_use", "id": "c1", "name": "get_kpis", "input": {}}], "max_tokens")
    model.replies.append(cut)
    client.post("/api/chat", headers=headers, json={"question": "Фудкост?", "thread_id": thread})
    model.replies += [text_reply("Вы теряете 48 000 ₽."), text_reply("Нет, 51 000 ₽.")]
    shown = client.post(
        "/api/chat", headers=headers, json={"question": "Сколько?", "thread_id": thread}
    ).json()
    model.replies.append(text_reply("Хорошо."))
    client.post("/api/chat", headers=headers, json={"question": "Спасибо", "thread_id": thread})

    replayed = model.requests[-1].messages
    roles = [m["role"] for m in replayed]
    assert roles == ["user", "assistant"] * 3 + ["user"]  # question, answer — no gaps, no leftovers
    texts = [m["content"][0]["text"] for m in replayed if m["role"] == "assistant"]
    assert texts[0].startswith("На этот вопрос я не отвечу") and texts[1].startswith(
        "Ответ получился слишком"
    )
    assert texts[2] == shown["text"] and "48" not in json.dumps(replayed, ensure_ascii=False)
    assert all(b.get("type") != "tool_use" for m in replayed for b in m["content"])


def test_two_questions_to_one_thread_at_once_are_kept_one_after_the_other(network: Network) -> None:
    """Code review 28.10.2026, stage 5, p. 8: the thread row is locked while a question is appended."""
    import threading

    from app.ai import history
    from app.tenancy.context import tool_session

    with tool_session(network.a.users["director1@a.ru"], network.a.id) as (_, ctx):
        pass
    thread = history.start(ctx, title="?", finding_id=None)
    barrier, errors = threading.Barrier(2), []

    def ask(n: int) -> None:
        barrier.wait()
        try:
            msgs = [
                {"role": "user", "content": [{"type": "text", "text": f"q{n}"}]},
                {"role": "assistant", "content": [{"type": "text", "text": f"a{n}"}]},
            ]
            history.append(ctx, thread, msgs, question=f"q{n}", answer=f"a{n}")
        except Exception as exc:
            errors.append(exc)

    workers = [threading.Thread(target=ask, args=(n,)) for n in (1, 2)]
    for w in workers:
        w.start()
    for w in workers:
        w.join()
    assert errors == [] and len(history.replay(ctx, thread)) == 4


def test_a_tool_that_fails_is_an_answer_for_the_model(
    client: TestClient, network: Network, model: FakeModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Code review 28.10.2026, stage 5, p. 9."""
    from app.ai import tools

    def broken(*_: Any) -> dict[str, Any]:
        raise RuntimeError("db down")

    monkeypatch.setitem(
        tools.TOOLS, "get_tasks", tools.TOOLS["get_tasks"].__class__("get_tasks", "…", tools.NoArgs, broken)
    )
    model.replies += [tool_reply("get_tasks", {}), text_reply("Задачи сейчас не получить.")]
    r = client.post("/api/chat", headers=login(client, "director1@a.ru"), json={"question": "Задачи?"})
    assert r.status_code == 200 and r.json()["text"] == "Задачи сейчас не получить."
    assert json.loads(model.requests[1].messages[-1]["content"][0]["content"]) == {
        "error": "Не удалось получить данные"
    }


def test_no_connection_waits_in_a_transaction_while_the_model_thinks(
    client: TestClient, network: Network, model: FakeModel, owner_engine: Any
) -> None:
    """Code review 28.10.2026, stage 5, p. 4: the request's transaction ends before the model is called."""
    from sqlalchemy.pool import QueuePool

    from app.core.db import get_engine

    seen: list[int] = []

    def probe(_: ModelRequest) -> Reply:
        pool = get_engine().pool
        assert isinstance(pool, QueuePool)
        seen.append(
            pool.checkedout()
        )  # connections the application holds right now  # connections the application holds right now
        return text_reply("Ответ")

    headers = login(client, "director1@a.ru")
    for path in ("/api/chat", "/api/chat/stream"):
        model.replies.append(probe)
        assert client.post(path, headers=headers, json={"question": "?"}).status_code == 200
    assert seen == [0, 0]


def test_the_budget_counts_once_per_question_and_a_started_question_is_finished(
    client: TestClient, network: Network
) -> None:
    """Code review 28.10.2026, stage 5, p. 10: a question takes a few calls; it is not cut in the middle."""
    fake = FakeModel([tool_reply("get_tasks", {}), text_reply("Задач нет."), text_reply("ещё")])
    app.dependency_overrides[get_gateway] = lambda: Gateway(fake, per_user_day=1)
    try:
        headers = login(client, "director1@a.ru")
        assert (
            client.post("/api/chat", headers=headers, json={"question": "Задачи?"}).json()["text"]
            == "Задач нет."
        )
        r = client.post("/api/chat", headers=headers, json={"question": "А ещё?"})
        assert r.status_code == 429 and "полночь" in r.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_gateway, None)
