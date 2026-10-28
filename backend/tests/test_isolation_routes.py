"""Every route of the API, walked for isolation (architecture review 27.10.2026, p. 21; CLAUDE.md, p. 2).

The routes are read from the OpenAPI schema, so a new endpoint is checked the day it appears: it has to fall
into one of the groups below, or this test fails and says where to put it.

- **Objects by id** (`/findings/{finding_id}`…): called with the ids of another network's finding, task,
  check, file, name match, restaurant — only 403 or 404, for the other network's admin and for a director.
- **Lists and screens** (GET without ids): another network's ids and names never appear in the answer; a
  director's answer holds no id of another restaurant of the network.
- **Writes that name an object in the body** (a task for a finding…): another network's id → not found.
- **Writes into one's own network** and **public** routes: listed by name, covered by their own tests.
"""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, fields
from datetime import date
from decimal import Decimal
from itertools import product
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.ai.models import ChatThread
from app.catalog.models import NameAlias, Product
from app.core.period import get_today
from app.experiments.models import Experiment
from app.imports.models import ImportBatch
from app.insights.models import Finding
from app.main import app
from app.tasks.models import Task
from tests.conftest import Network, login

TODAY = date(2026, 10, 20)

PUBLIC = {"GET /api/health", "POST /api/auth/login", "POST /api/auth/refresh"}
# Writes that create or change things of the caller's own network only; their rules have their own tests.
OWN_NETWORK = {
    "POST /api/restaurants",
    "POST /api/users",
    "PUT /api/settings/norms",
    "PUT /api/settings/engine",
    "POST /api/analytics/run",
    "POST /api/imports",
}
# Writes that name another object in the body: route → body, `{finding_id}` filled with the foreign id.
BODY_REFS = {
    "POST /api/tasks": {"title": "x", "due_on": "2026-10-30", "finding_id": "{finding_id}"},
    "POST /api/checks": {"finding_id": "{finding_id}", "action": "x", "control_ids": [], "weeks": 4},
    "POST /api/chat": {"question": "Почему так получилось?", "finding_id": "{finding_id}"},
    "POST /api/chat/stream": {"question": "Почему так получилось?", "finding_id": "{finding_id}"},
}
# Bodies that pass validation, so that a refusal is about access and not about the form (403 or 404 only).
BODIES: dict[str, dict[str, Any]] = {
    "POST /api/findings/{finding_id}/review": {"verdict": "confirm"},
    "POST /api/tasks/{task_id}/complete": {"report": "сделано"},
    "POST /api/tasks/{task_id}/checklist": {"index": 0, "done": True},
    "PUT /api/aliases/{alias_id}": {"target_id": "00000000-0000-0000-0000-000000000000"},
    "POST /api/imports/{batch_id}/match": {
        "matches": [{"kind": "product", "key": "x", "target_id": "00000000-0000-0000-0000-000000000000"}]
    },
}
QUERIES = {"GET /api/checks/draft": "finding_id={finding_id}"}
LISTS = {"kind": ["product", "menu_item", "supplier"]}  # path parameters that name a list, not an object


@dataclass
class Foreign:
    """Objects of network B, which network A's people must never reach."""

    finding_id: UUID
    task_id: UUID
    check_id: UUID
    batch_id: UUID
    alias_id: UUID
    thread_id: UUID
    restaurant_id: UUID
    code: str
    names: list[str]


@pytest.fixture
def foreign(network: Network, owner_engine: Engine) -> Foreign:
    b = network.b
    with Session(owner_engine, expire_on_commit=False) as s, s.begin():
        finding = Finding(
            tenant_id=b.id,
            restaurant_id=b.restaurants["B1"],
            kind="problem",
            process="production",
            title="Чужая находка сети Б",
            effect_rub_month=Decimal("1000.00"),
            actions=["Шаг"],
            found_on=TODAY,
        )
        s.add(finding)
        s.flush()
        check = Experiment(
            tenant_id=b.id,
            finding_id=finding.id,
            title="Чужая проверка сети Б",
            hypothesis="…",
            metric="…",
            test_restaurant_ids=[b.restaurants["B1"]],
            starts_on=TODAY,
            ends_on=date(2026, 11, 20),
            expected_rub_month=Decimal("500.00"),
            status="completed",
            verdict="confirmed",
            effect_rub_month=Decimal("500.00"),
            completed_on=TODAY,
        )
        task = Task(
            tenant_id=b.id,
            restaurant_id=b.restaurants["B1"],
            finding_id=finding.id,
            assigned_by="hq",
            title="Чужая задача сети Б",
            checklist=["Шаг"],
            checklist_done=[False],
            created_on=date(2026, 10, 1),
            due_on=date(2026, 10, 10),
        )
        item = Product(tenant_id=b.id, code="PB1", name="Чужой товар сети Б", base_unit="kg")
        batch = ImportBatch(
            tenant_id=b.id,
            restaurant_id=b.restaurants["B1"],
            template="receipts",
            filename="чужой_файл_сети_б.csv",
            sha256="0" * 64,
            raw=b"",
            status="validated",
        )
        s.add_all([check, task, item, batch])
        s.flush()
        alias = NameAlias(
            tenant_id=b.id,
            restaurant_id=None,
            kind="product",
            source_key="чужое название",
            source_text="Чужое название",
            target_id=item.id,
        )
        thread = ChatThread(tenant_id=b.id, user_id=b.users["admin@b.ru"], title="Чужой разговор сети Б")
        s.add_all([alias, thread])
        s.flush()
        return Foreign(
            finding.id,
            task.id,
            check.id,
            batch.id,
            alias.id,
            thread.id,
            b.restaurants["B1"],
            "B1",
            [
                "Чужая находка сети Б",
                "Чужая задача сети Б",
                "Чужая проверка сети Б",
                "Чужой товар сети Б",
                "чужой_файл_сети_б.csv",
                "Чужой разговор сети Б",
            ],
        )


@pytest.fixture(autouse=True)
def _pin_today() -> Any:
    app.dependency_overrides[get_today] = lambda: TODAY
    yield
    app.dependency_overrides.pop(get_today, None)


def _routes() -> list[tuple[str, str]]:
    return [(m.upper(), p) for p, methods in app.openapi()["paths"].items() for m in methods]


def _fill(template: str, ids: dict[str, str]) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: ids[m.group(1)], template)


def _ids(f: Foreign) -> dict[str, str]:
    return {
        "finding_id": str(f.finding_id),
        "task_id": str(f.task_id),
        "check_id": str(f.check_id),
        "batch_id": str(f.batch_id),
        "alias_id": str(f.alias_id),
        "thread_id": str(f.thread_id),
        "restaurant_id": str(f.restaurant_id),
        "code": f.code,
    }


def _call(client: TestClient, method: str, path: str, headers: dict[str, str], body: Any = None) -> Any:
    return client.request(method, path, headers=headers, json=body if method in ("POST", "PUT") else None)


def test_every_route_is_walked_for_isolation() -> None:
    """A new endpoint must be placed in a group here — that is the decision about how it is isolated."""
    unplaced = [
        f"{m} {p}"
        for m, p in _routes()
        if f"{m} {p}" not in PUBLIC | OWN_NETWORK | set(BODY_REFS) and "{" not in p and m != "GET"
    ]
    assert unplaced == [], f"add these routes to a group of tests/test_isolation_routes.py: {unplaced}"
    params = {name for _, p in _routes() for name in re.findall(r"\{(\w+)\}", p)}
    known = {f.name for f in fields(Foreign)} - {"names"} | set(LISTS)
    assert params <= known, "a new kind of id: add it to Foreign"


def _names_an_object(path: str) -> bool:
    return any(name not in LISTS for name in re.findall(r"\{(\w+)\}", path))


def _lists(path: str) -> list[str]:
    """The path for every value of its list parameters (`/catalog/{kind}` → three lists)."""
    paths = [path]
    for name, values in LISTS.items():
        if f"{{{name}}}" in path:
            paths = [p.replace(f"{{{name}}}", v) for p in paths for v in values]
    return paths


def test_another_networks_objects_are_never_reached_by_id(
    client: TestClient, network: Network, foreign: Foreign
) -> None:
    ids = _ids(foreign)
    people = {"admin": login(client, "admin@a.ru"), "director": login(client, "director1@a.ru")}
    reached = []
    for method, path in _routes():
        key = f"{method} {path}"
        if not _names_an_object(path) and key not in QUERIES:
            continue
        url = _fill(path, ids) + (f"?{_fill(QUERIES[key], ids)}" if key in QUERIES else "")
        for who, headers in people.items():
            r = _call(client, method, url, headers, BODIES.get(key, {}))
            if r.status_code not in (403, 404):
                reached.append(f"{who}: {key} → {r.status_code} {r.text[:200]}")
    assert reached == [], reached


def test_writes_naming_another_networks_object_are_refused(
    client: TestClient, network: Network, foreign: Foreign
) -> None:
    ids = _ids(foreign)
    admin = login(client, "admin@a.ru")
    for key, template in BODY_REFS.items():
        method, path = key.split(" ", 1)
        body = json.loads(_fill(json.dumps(template), ids))
        r = _call(client, method, path, admin, body)
        if key.startswith("POST /api/chat"):  # answers, but never about another network's finding
            assert r.status_code == 200 and not any(n in r.text for n in foreign.names), r.text[:300]
        else:
            assert r.status_code in (403, 404), f"{key} → {r.status_code} {r.text[:200]}"


def test_lists_and_screens_hold_nothing_of_another_network_or_restaurant(
    client: TestClient, network: Network, foreign: Foreign
) -> None:
    a = network.a
    others = [str(a.restaurants[c]) for c in ("A2", "A3")]  # director1 runs A1
    people = {"admin": login(client, "admin@a.ru"), "director": login(client, "director1@a.ru")}
    leaks = []
    for method, path in _routes():
        if method != "GET" or _names_an_object(path) or f"{method} {path}" in PUBLIC | set(QUERIES):
            continue
        for (who, headers), url in product(people.items(), _lists(path)):
            r = client.get(url, headers=headers)
            if r.status_code >= 300:
                continue
            body = r.text
            for marker in [str(foreign.finding_id), str(foreign.restaurant_id), *foreign.names]:
                if marker in body:
                    leaks.append(f"{who}: GET {url} shows another network's {marker}")
            if who == "director":
                leaks += [f"director: GET {url} shows restaurant {rid}" for rid in others if rid in body]
    assert leaks == [], leaks


def test_the_assistant_through_the_model_holds_nothing_of_another_network(
    client: TestClient, network: Network, foreign: Foreign
) -> None:
    """Code review 28.10.2026, stage 5, p. 18: the chat's model path walked like the routes — every tool is
    called (also with another network's ids) and its results quoted back; neither the answer nor anything sent
    to the model holds another network's ids or names."""
    from app.ai import tools
    from app.ai.gateway import FakeModel, Gateway, ModelRequest, Reply, Usage, get_gateway, text_reply

    args = {
        "get_findings": {"restaurant_code": foreign.code},
        "explain_finding": {"finding_id": str(foreign.finding_id)},
        "search_products": {"query": "Чужой"},
        "get_purchase_prices": {"product": "Чужой", "days": 180},
    }

    def call_all(_: ModelRequest) -> Reply:
        blocks = [
            {"type": "tool_use", "id": f"c{i}", "name": name, "input": args.get(name, {})}
            for i, name in enumerate(tools.TOOLS)
        ]
        return Reply(blocks, "tool_use", Usage(1, 1))

    def quote(r: ModelRequest) -> Reply:
        results = [b["content"] for b in r.messages[-1]["content"] if b.get("type") == "tool_result"]
        return text_reply("\n".join(results))

    def gateway_of(model: FakeModel) -> Callable[[], Gateway]:
        return lambda: Gateway(model, per_user_day=100)

    for who in ("admin@a.ru", "director1@a.ru"):
        model = FakeModel([call_all, quote])
        app.dependency_overrides[get_gateway] = gateway_of(model)
        try:
            body = {"question": "Расскажи всё", "finding_id": str(foreign.finding_id)}
            r = client.post("/api/chat", headers=login(client, who), json=body)
        finally:
            app.dependency_overrides.pop(get_gateway, None)
        assert r.status_code == 200 and len(model.requests) == 2
        # What the server gave the model (the question and the tools' results) and the answer — not the
        # arguments the model itself chose.
        given = [
            b.get("content") or b.get("text")
            for m in model.requests[-1].messages
            if m["role"] == "user"
            for b in m["content"]
        ]
        sent = json.dumps(given, ensure_ascii=False) + r.text
        markers = [str(foreign.finding_id), str(foreign.restaurant_id), *foreign.names]
        assert [m for m in markers if m in sent] == [], who
