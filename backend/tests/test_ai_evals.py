"""The chat's eval set and its runner (docs/08, «Качество»), checked without the real model: every expected
figure is computed from the demo data, a model that does it right scores 100 %, a leaking or inventing one is
caught. The score of the real model is measured by `python -m app.ai.evals` once the key comes (Q12)."""

from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.ai import evals, tools
from app.ai.gateway import Gateway, ModelRequest, Reply, Usage, text_reply
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
