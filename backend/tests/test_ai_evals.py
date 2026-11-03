"""The chat's eval set and its runner (docs/08, «Качество»), checked without the real model: every expected
figure is computed from the demo data, a model that does it right scores 100 %, a leaking or inventing one is
caught. The score of the real model is measured by `python -m app.ai.evals` once the key comes (Q12)."""

import json
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.ai import evals, tools
from app.ai.evals import digest as digest_eval
from app.ai.gateway import FakeModel, Gateway, ModelRequest, Reply, Usage, text_reply
from app.tenancy.context import AccessContext
from app.tenancy.permissions import Permission
from tests.conftest import Network
from tests.test_overview import TODAY, demo  # noqa: F401  (the demo network: tenant A, director r01@a.ru)

DEFAULT_ARGS = {
    "search_products": {"query": "сыр"},
    "get_purchase_prices": {"product": "лосось", "days": 30},
    "explain_finding": {"finding_id": "{own}"},
}


@pytest.fixture
def world(network: Network, owner_engine: Engine, demo: dict[str, UUID]) -> evals.World:  # noqa: F811
    with Session(owner_engine) as s:
        return evals.world_from(s, director_email="r01@a.ru", hq_email="admin@a.ru")


class Oracle:
    """Answers every case the way it should be answered: calls the tools that compute the expected figures
    and quotes them; refuses what is not the person's. `leak` and `invent` spoil it on purpose."""

    def __init__(self, world: evals.World, *, leak: bool = False, invent: bool = False) -> None:
        self.world, self.leak, self.invent = world, leak, invent
        self.cases = {(c["question"], c.get("finding")): c for c in evals.load_cases()}

    def _case(self, request: ModelRequest) -> dict[str, Any]:
        first = request.messages[0]["content"][0]["text"]
        kind = next((k for k, fid in self.world.findings.items() if str(fid) in first), None)
        return self.cases[(first.split("\n")[-1], kind)]

    def complete(self, request: ModelRequest) -> Reply:
        case = self._case(request)
        last = request.messages[-1]["content"]
        answered = any(b.get("type") == "tool_result" for b in last)
        if case.get("leak"):
            name = self.world.leak_markers[case["who"]][0] if self.leak else "другие рестораны"
            return text_reply(f"Данные о {name} вам недоступны.")
        if case["tools"] and not answered:
            calls = [(f["tool"], f.get("args", {})) for f in case["facts"]] or [
                (case["tools"][0], DEFAULT_ARGS.get(case["tools"][0], {}))
            ]
            unique = list({(t, str(a)): (t, a) for t, a in calls}.values())
            blocks = [
                {"type": "tool_use", "id": f"call_{i}", "name": t, "input": evals._fill(a, self.world)}
                for i, (t, a) in enumerate(unique)
            ]
            return Reply(blocks, "tool_use", Usage(10, 10))
        figures = evals.expected(case, self.world, TODAY)
        text = "По данным: " + "; ".join(figures) if figures else "Вот что я нашел в данных."
        return text_reply(text + (" Итого 987 654 ₽." if self.invent else ""))


def test_every_case_is_well_formed_and_its_figures_are_computed_from_the_data(world: evals.World) -> None:
    cases = evals.load_cases()
    assert len(cases) >= 40 and len({c["id"] for c in cases}) == len(cases)
    leaks = [c for c in cases if c.get("leak")]
    assert len(leaks) >= 6 and {c["who"] for c in cases} == {"director", "hq"}
    for case in cases:
        assert set(case["tools"]) <= set(tools.TOOLS), case["id"]
        if case["who"] == "director":  # the director's cases use only the director's tools
            hq_only = [t for t in case["tools"] if tools.TOOLS[t].permission == Permission.NETWORK_COMPARE]
            assert hq_only == [], case["id"]
        figures = evals.expected(case, world, TODAY)
        assert all(f not in ("None", "") for f in figures), (case["id"], figures)


def test_a_model_that_answers_right_scores_full_marks(world: evals.World) -> None:
    report = evals.run(Gateway(Oracle(world), per_user_day=10_000), world, TODAY)
    assert report.summary().startswith("Верно: 40 из 40 (100%), утечек: 0"), report.summary()
    assert report.passed


def test_a_leak_fails_the_run_whatever_the_score(world: evals.World) -> None:
    report = evals.run(Gateway(Oracle(world, leak=True), per_user_day=10_000), world, TODAY)
    assert report.leaks >= 6 and not report.passed
    assert all(o.leaked for o in report.outcomes if o.id.startswith("d-leak"))


def test_an_invented_figure_is_not_counted_as_correct(world: evals.World) -> None:
    report = evals.run(Gateway(Oracle(world, invent=True), per_user_day=10_000), world, TODAY)
    wrong = [o for o in report.outcomes if not o.correct]
    assert wrong and all("987654" in " ".join(o.problems) for o in wrong)
    assert report.score < evals.TARGET and not report.passed


# ------------------------------------------------------------------ the digest texts' eval (stage 6)


def _digest_cases(network: Network, owner_engine: Engine) -> tuple[list[digest_eval.Case], AccessContext]:
    from app.core.db import get_sessionmaker
    from app.digests import weekly
    from app.tenancy.context import load_access_context

    weekly.run(network.a.id, TODAY)
    with Session(owner_engine) as s:
        all_cases = digest_eval.cases(s, network.a.id)
    with get_sessionmaker()() as s:
        ctx = load_access_context(s, network.a.users["admin@a.ru"], network.a.id)
    assert ctx is not None
    return all_cases, ctx


def _writer(spoil: str = "") -> Any:
    """Writes every digest from its own facts; `spoil` adds jargon, a greeting or another restaurant."""

    def reply(request: ModelRequest) -> Reply:
        facts = json.loads(request.messages[0]["content"][0]["text"].split("\n", 1)[1])
        ids = [i["finding_id"] for i in facts["problems"] + facts["opportunities"] + facts["risks"]]
        total = facts["on_table"]["total"]
        headline = f"На столе {total} в месяц. Начните с главного пункта.{spoil}"
        body = {
            "headline": headline,
            "items": [{"finding_id": i, "text": "Проверьте накладные."} for i in ids],
        }
        return text_reply(json.dumps(body, ensure_ascii=False))

    return reply


@pytest.mark.usefixtures("demo")
def test_the_digest_eval_passes_good_texts_and_catches_bad_ones(
    network: Network, owner_engine: Engine
) -> None:
    all_cases, ctx = _digest_cases(network, owner_engine)
    assert {c.scope for c in all_cases} >= {"сеть", "R01"}
    good = digest_eval.run(
        Gateway(FakeModel([_writer() for _ in range(40)]), per_user_day=10_000), ctx, all_cases
    )
    assert good.passed and good.score == 1.0, good.summary()

    r01 = [c for c in all_cases if c.scope == "R01"]
    other = r01[0].others[0]
    for spoil, problem in ((" Это видно по M1.", "коды модулей"), (" Здравствуйте!", "приветствие")):
        bad = digest_eval.run(Gateway(FakeModel([_writer(spoil)]), per_user_day=10_000), ctx, r01)
        assert not bad.outcomes[0].ok and problem in bad.summary()
    leak = digest_eval.run(Gateway(FakeModel([_writer(f" Как в {other}.")]), per_user_day=10_000), ctx, r01)
    assert leak.outcomes[0].leak and not leak.passed and "УТЕЧКА" in leak.summary()


@pytest.mark.usefixtures("demo")
def test_a_text_that_falls_back_to_the_rules_is_a_miss(network: Network, owner_engine: Engine) -> None:
    all_cases, ctx = _digest_cases(network, owner_engine)
    net = [c for c in all_cases if c.scope == "сеть"]
    invented = text_reply(json.dumps({"headline": "На столе 999 999 ₽.", "items": []}, ensure_ascii=False))
    report = digest_eval.run(Gateway(FakeModel([invented, invented]), per_user_day=10_000), ctx, net)
    assert not report.passed and "по правилам" in report.summary()
    assert digest_eval.check(net[0], {"headline": "Раз. Два. Три. Четыре.", "items": {}}).problems == [
        "«Главное за неделю» — 4 предложений, нужно 1–3"
    ]
