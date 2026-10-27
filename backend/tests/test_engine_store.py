"""TC-ENG-11/12: how one engine run writes its findings (docs/12, «Конвейер»; app/analytics/engine.py).

The engine matches findings by `key`. A finding it no longer finds disappears only if nobody has worked on it;
a finding a person has touched (task, check, rejection, status) stays for a person to close.
"""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.analytics import engine
from app.core.db import get_sessionmaker
from app.experiments.models import Experiment
from app.insights.models import Finding
from app.tasks.models import Task
from app.tenancy.context import load_access_context
from tests.conftest import Network

TODAY = date(2026, 10, 25)


def _finding(tenant: UUID, restaurant: UUID | None, title: str, **kw: Any) -> Finding:
    values: dict[str, Any] = {
        "kind": "problem",
        "process": "production",
        "effect_rub_month": Decimal("1000.00"),
        "actions": [],
        "found_on": date(2026, 10, 1),
        "status": "new",
        "review_status": "confirmed",
    }
    values.update(kw)
    return Finding(tenant_id=tenant, restaurant_id=restaurant, title=title, **values)


def _titles(owner_engine: Engine) -> set[str]:
    with owner_engine.connect() as c:
        return set(c.execute(text("SELECT title FROM findings")).scalars())


def test_stale_findings_go_only_if_nobody_has_worked_on_them(network: Network, owner_engine: Engine) -> None:
    """TC-ENG-12. The network has no data, so the run finds nothing and every engine finding is stale."""
    a, a1 = network.a.id, network.a.restaurants["A1"]
    with Session(owner_engine) as s, s.begin():
        untouched = _finding(a, a1, "untouched", key="M1:A1:P1", module="M1", review_status="pending")
        with_task = _finding(a, a1, "with a task", key="M1:A1:P2", module="M1")
        with_check = _finding(a, a1, "with a check", key="M3:A1:P3", module="M3")
        rejected = _finding(a, a1, "rejected", key="M2:A1:D1", module="M2", review_status="rejected")
        in_work = _finding(a, a1, "in work", key="M4:A1:P4", module="M4", status="in_work")
        resolved = _finding(
            a, a1, "resolved", key="M5:A1:P5", module="M5", status="resolved", resolved_on=date(2026, 10, 2)
        )
        other_module = _finding(a, a1, "other module", key="M9:A1:P6", module="M9")
        by_hand = _finding(a, a1, "made by hand", review_status=None)
        foreign = _finding(network.b.id, network.b.restaurants["B1"], "foreign", key="M1:B1:P1", module="M1")
        s.add_all(
            [untouched, with_task, with_check, rejected, in_work, resolved, other_module, by_hand, foreign]
        )
        s.flush()
        s.add(
            Task(
                tenant_id=a,
                restaurant_id=a1,
                finding_id=with_task.id,
                title="Шаг",
                assigned_by="hq",
                created_on=date(2026, 10, 2),
                due_on=date(2026, 10, 30),
            )
        )
        s.add(
            Experiment(
                tenant_id=a,
                finding_id=with_check.id,
                title="Проверка",
                hypothesis="…",
                metric="цена",
                test_restaurant_ids=[a1],
                starts_on=date(2026, 10, 27),
                ends_on=date(2026, 11, 24),
                expected_rub_month=Decimal("600.00"),
            )
        )

    with get_sessionmaker()() as session:
        ctx = load_access_context(session, network.a.users["admin@a.ru"], a)
        assert ctx is not None
        result = engine.run(session, ctx, TODAY)
        session.commit()

    # Only the finding nobody touched goes; the other network is not even seen.
    assert (result.created, result.updated, result.removed, result.drafts) == (0, 0, 1, 0)
    assert _titles(owner_engine) == {
        "with a task",
        "with a check",
        "rejected",
        "in work",
        "resolved",
        "other module",
        "made by hand",
        "foreign",
    }


def test_two_findings_with_one_key_stop_the_run(
    network: Network, owner_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TC-ENG-11. Two drafts with one key would be written into one finding: the run refuses,
    nothing changes."""
    a, a1 = network.a.id, network.a.restaurants["A1"]
    with Session(owner_engine) as s, s.begin():
        s.add(_finding(a, a1, "before the run", key="M1:A1:P1", module="M1", review_status="pending"))
    twins = [SimpleNamespace(key="M1:A1:P1"), SimpleNamespace(key="M1:A1:P1")]
    monkeypatch.setattr(engine, "analyse", lambda *_args, **_kw: (twins, []))

    with get_sessionmaker()() as session:
        ctx = load_access_context(session, network.a.users["admin@a.ru"], a)
        assert ctx is not None
        with pytest.raises(RuntimeError, match="duplicate finding keys: \\['M1:A1:P1'\\]"):
            engine.run(session, ctx, TODAY)
        session.rollback()

    # The stale finding was not removed and no run was audited.
    assert _titles(owner_engine) == {"before the run"}
    with owner_engine.connect() as c:
        assert (
            c.execute(text("SELECT count(*) FROM audit_log WHERE action = 'analytics.run'")).scalar_one() == 0
        )


def test_the_engine_refuses_to_run_outside_the_networks_context(
    network: Network, owner_engine: Engine
) -> None:
    """Architecture review 27.10.2026, p. 9: under the owner role (no row-level security) or another network's
    context the engine would read and replace every network's rows — it refuses instead."""
    with get_sessionmaker()() as session:
        ctx = load_access_context(session, network.a.users["admin@a.ru"], network.a.id)
        assert ctx is not None
    # A script run as the owner: no context at all, and even with the network's context set.
    with Session(owner_engine) as owner, pytest.raises(RuntimeError, match="row-level security context"):
        engine.run(owner, ctx, date(2026, 10, 20))
    with Session(owner_engine) as owner, pytest.raises(RuntimeError, match="row-level security context"):
        owner.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(network.a.id)})
        engine.run(owner, ctx, date(2026, 10, 20))
    with get_sessionmaker()() as session, pytest.raises(RuntimeError, match="row-level security context"):
        load_access_context(session, network.b.users["admin@b.ru"], network.b.id)  # network B's context
        engine.run(session, ctx, date(2026, 10, 20))
