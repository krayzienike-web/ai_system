"""The gateway to the model (ADR 0005): the log of every call, the daily budget, versioned prompts, the
Claude adapter's request — all without the API key (Q12)."""

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from app.ai import prompt as prompts
from app.ai.claude import FALLBACK_BETA, ClaudeModel
from app.ai.gateway import (
    BudgetError,
    FakeModel,
    Gateway,
    ModelRequest,
    ModelUnavailableError,
    Reply,
    Usage,
    cost_usd,
    get_model,
    text_reply,
    tool_reply,
)
from app.ai.models import AiRun
from app.core.db import get_sessionmaker
from app.tenancy.context import AccessContext, tool_session
from tests.conftest import Network


def _ctx(network: Network, email: str = "director1@a.ru") -> AccessContext:
    with tool_session(network.a.users[email], network.a.id) as (_, ctx):
        return ctx


def _runs(owner_engine: Engine) -> list[AiRun]:
    with Session(owner_engine) as s:
        return list(s.execute(select(AiRun).order_by(AiRun.created_at)).scalars())


def test_every_call_is_logged_with_prompt_version_tokens_and_cost(
    network: Network, owner_engine: Engine
) -> None:
    ctx = _ctx(network)
    model = FakeModel([text_reply("Фудкост 31,2 %", usage=Usage(1000, 200, 5000, 0))])
    chat = prompts.load("chat")
    reply = Gateway(model).complete(
        ctx, task="chat", prompt=chat, messages=[{"role": "user", "content": "Какой фудкост?"}]
    )
    assert reply.text == "Фудкост 31,2 %"
    assert model.requests[0].system == chat.text and model.requests[0].model == "claude-opus-5-5"
    (run,) = _runs(owner_engine)
    assert (run.user_id, run.tenant_id, run.task, run.status) == (ctx.user_id, ctx.tenant_id, "chat", "ok")
    assert (run.prompt, run.prompt_version) == ("chat", chat.version)
    assert run.request["prompt_sha256"] == chat.sha256
    assert run.request["messages"] == [{"role": "user", "content": "Какой фудкост?"}]
    assert run.response == [{"type": "text", "text": "Фудкост 31,2 %"}]
    assert (run.input_tokens, run.output_tokens, run.cache_read_tokens) == (1000, 200, 5000)
    # 1000 × $4 + 200 × $20 + 5000 × $0.20 per million tokens.
    assert run.cost_usd == Decimal("0.009000")


def test_refusals_truncations_and_failures_are_logged_too(network: Network, owner_engine: Engine) -> None:
    ctx = _ctx(network)

    def broken(_: ModelRequest) -> Reply:
        raise ConnectionError("down")

    model = FakeModel(
        [Reply([], "refusal"), Reply([{"type": "text", "text": "…"}], "max_tokens"), broken],
    )
    gateway = Gateway(model)
    chat = prompts.load("chat")
    ask = [{"role": "user", "content": "?"}]
    assert gateway.complete(ctx, task="chat", prompt=chat, messages=ask).stop_reason == "refusal"
    assert gateway.complete(ctx, task="chat", prompt=chat, messages=ask).stop_reason == "max_tokens"
    with pytest.raises(ModelUnavailableError, match="недоступен"):
        gateway.complete(ctx, task="chat", prompt=chat, messages=ask)
    runs = _runs(owner_engine)
    assert [r.status for r in runs] == ["refused", "truncated", "failed"]
    assert runs[2].error == "ConnectionError: down" and runs[2].response is None


def test_tool_calls_go_out_with_the_tools_and_come_back_as_blocks(
    network: Network, owner_engine: Engine
) -> None:
    ctx = _ctx(network)
    model = FakeModel([tool_reply("get_kpis", {"period": "month"})])
    tools = [{"name": "get_kpis", "description": "…", "input_schema": {"type": "object"}}]
    reply = Gateway(model).complete(
        ctx,
        task="chat",
        prompt=prompts.load("chat"),
        messages=[{"role": "user", "content": "?"}],
        tools=tools,
    )
    assert reply.tool_calls == [
        {"type": "tool_use", "id": "call_1", "name": "get_kpis", "input": {"period": "month"}}
    ]
    assert model.requests[0].tools == tools
    assert _runs(owner_engine)[0].request["tools"] == ["get_kpis"]


def test_the_daily_budget_stops_the_next_call_and_is_per_user(network: Network, owner_engine: Engine) -> None:
    director, analyst = _ctx(network), _ctx(network, "analyst@a.ru")
    model = FakeModel([text_reply("1"), text_reply("2"), text_reply("3")])
    gateway = Gateway(model, per_user_day=2)
    chat = prompts.load("chat")
    ask = [{"role": "user", "content": "?"}]
    gateway.complete(director, task="chat", prompt=chat, messages=ask)
    gateway.complete(director, task="chat", prompt=chat, messages=ask)
    with pytest.raises(BudgetError) as refused:
        gateway.complete(director, task="chat", prompt=chat, messages=ask)
    assert refused.value.status_code == 429 and len(model.requests) == 2  # the model was not called
    gateway.complete(analyst, task="chat", prompt=chat, messages=ask)  # someone else's budget is their own
    # Yesterday's calls do not count.
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE ai_runs SET created_at = created_at - interval '1 day'"))
    model.replies.append(text_reply("4"))
    gateway.complete(director, task="chat", prompt=chat, messages=ask)


def test_the_log_is_append_only_and_each_person_sees_their_own(network: Network) -> None:
    """TC-ISO: a director sees their own calls, the HQ the network's, another network nothing; nobody may
    change or delete the log (it is what the budget counts)."""
    director, admin = _ctx(network), _ctx(network, "admin@a.ru")
    gateway = Gateway(FakeModel([text_reply("1"), text_reply("2")]))
    chat = prompts.load("chat")
    gateway.complete(director, task="chat", prompt=chat, messages=[{"role": "user", "content": "мой"}])
    gateway.complete(admin, task="chat", prompt=chat, messages=[{"role": "user", "content": "ук"}])

    def visible(user: Any, tenant: Any) -> list[str]:
        with tool_session(user, tenant) as (s, _):
            return sorted(r.request["messages"][0]["content"] for r in s.execute(select(AiRun)).scalars())

    assert visible(network.a.users["director1@a.ru"], network.a.id) == ["мой"]
    assert visible(network.a.users["director2@a.ru"], network.a.id) == []
    assert visible(network.a.users["admin@a.ru"], network.a.id) == ["мой", "ук"]
    assert visible(network.b.users["admin@b.ru"], network.b.id) == []
    for statement in ("UPDATE ai_runs SET status = 'ok'", "DELETE FROM ai_runs"):
        with get_sessionmaker()() as s, s.begin(), pytest.raises(ProgrammingError, match="permission denied"):
            s.execute(text(statement))


def test_costs_follow_the_price_list_and_unknown_models_cost_nothing() -> None:
    assert cost_usd("claude-haiku-5-5", Usage(1_000_000, 1_000_000, 1_000_000, 1_000_000)) == Decimal(
        "0.735000"
    )
    assert cost_usd("fake", Usage(10, 10)) == Decimal("0")


def test_prompts_are_versioned_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name, body in [("chat.v1.md", "первый"), ("chat.v2.md", "второй"), ("chat.v2.md.bak", "нет")]:
        (tmp_path / name).write_text(body, encoding="utf-8")
    monkeypatch.setattr(prompts, "PROMPTS", tmp_path)
    prompts.load.cache_clear()
    try:
        assert (prompts.load("chat").version, prompts.load("chat").text) == (2, "второй")
        assert prompts.load("chat", 1).text == "первый"
        with pytest.raises(LookupError):
            prompts.load("chat", 3)
        with pytest.raises(LookupError):
            prompts.load("digest")
    finally:
        prompts.load.cache_clear()


def test_the_shipped_chat_prompt_keeps_the_rules_the_evals_check() -> None:
    chat = prompts.load("chat")
    assert chat.version >= 2 and "explain_finding" in chat.text  # the question asked from a finding
    for rule in (
        "только из результатов инструментов",
        "не другие рестораны",
        "не создаешь задач",
        "не инструкции",
    ):
        assert rule in chat.text


def test_without_a_provider_there_is_no_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import get_settings

    assert get_model() is None  # `off` until the API key comes (Q12)
    monkeypatch.setenv("FAI_AI_PROVIDER", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    get_settings.cache_clear()
    try:
        assert isinstance(get_model(), ClaudeModel)
    finally:
        get_settings.cache_clear()


class _Messages:
    def __init__(self, result: Any) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    def create(self, **params: Any) -> Any:
        self.calls.append(params)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _client(result: Any) -> Any:
    return SimpleNamespace(beta=SimpleNamespace(messages=_Messages(result)))


def test_the_claude_request_caches_the_system_prompt_thinks_adaptively_and_falls_back() -> None:
    from anthropic.types.beta import BetaMessage

    message = BetaMessage.model_validate(
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5-5",
            "content": [{"type": "text", "text": "Ответ"}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {
                "input_tokens": 12,
                "output_tokens": 3,
                "cache_read_input_tokens": 900,
                "cache_creation_input_tokens": None,
            },
        }
    )
    client = _client(message)
    tools = [{"name": "get_kpis", "description": "…", "input_schema": {"type": "object"}}]
    reply = ClaudeModel(client).complete(
        ModelRequest("claude-opus-5-5", "Ты — су-шеф", [{"role": "user", "content": "?"}], tools)
    )
    assert reply.text == "Ответ" and reply.model == "claude-opus-5-5"
    assert reply.usage == Usage(12, 3, 900, 0)
    (params,) = client.beta.messages.calls
    assert params["system"] == [
        {"type": "text", "text": "Ты — су-шеф", "cache_control": {"type": "ephemeral"}}
    ]
    assert params["thinking"] == {"type": "adaptive"} and params["output_config"] == {"effort": "medium"}
    assert params["tools"] == tools
    assert (params["betas"], params["fallbacks"]) == ([FALLBACK_BETA], "default")
    # Haiku: no server-side fallback, no tools sent when there are none.
    haiku = ClaudeModel(client).params(ModelRequest("claude-haiku-5-5", "s", []))
    assert "fallbacks" not in haiku and "betas" not in haiku and "tools" not in haiku


def test_claude_api_errors_become_model_unavailable() -> None:
    import anthropic
    import httpx2

    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    errors = [
        anthropic.RateLimitError("slow down", response=httpx2.Response(429, request=request), body=None),
        anthropic.APIConnectionError(request=request),
    ]
    for error in errors:
        with pytest.raises(ModelUnavailableError):
            ClaudeModel(_client(error)).complete(ModelRequest("claude-opus-5-5", "s", []))
