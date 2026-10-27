"""Records the API's answers on the demo network for the standalone prototype (ADR 0007).

`python -m app.demo.snapshot` signs in as every demo user, calls every GET the screens use (with the demo's
«today») and writes `frontend/src/api/demo/snapshot.json`. The prototype replays these answers, so it shows
exactly what the backend computed; nothing is computed in the browser.

Run on a database prepared with `seed-demo` and `load-demo`.
"""

import json
from datetime import date
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.cli import DEMO_TODAY
from app.core.period import get_today
from app.main import app

OUT = Path(__file__).resolve().parents[3] / "frontend" / "src" / "api" / "demo" / "snapshot.json"
PASSWORD = "demo12345"  # noqa: S105 - the demo users' password, set by seed-demo
USERS = [
    "admin@demo.local",
    "analyst@demo.local",
    "director1@demo.local",
    "director2@demo.local",
    "director3@demo.local",
]
PRESETS = ["week", "prev_week", "4w", "13w", "month"]
# Board variants recorded to check the prototype's filtering against the server's (frontend contract test).
BOARD_CHECKS = ["kind=problem", "stage=doing", "late=true", "restaurant=net", "process=purchasing"]


def record(client: TestClient, email: str) -> dict[str, Any]:
    token = client.post("/api/auth/login", json={"email": email, "password": PASSWORD}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    answers: dict[str, Any] = {}

    def get(path: str) -> Any:
        response = client.get(f"/api{path}", headers=headers)
        if response.status_code == 200:
            answers[path] = response.json()
            return answers[path]
        return None

    me = get("/auth/me")
    hq = me["role"] != "restaurant_director"
    for path in (
        "/restaurants",
        "/overview/context",
        "/overview/badges",
        "/overview/findings",
        "/findings",
        "/tasks",
        "/tasks?late=true",
        "/chat/suggestions",
        "/settings/norms",
        "/settings/engine",
        "/imports",
        "/imports/templates",
        "/imports/freshness",
        "/aliases",
        "/catalog/product",
        "/catalog/menu_item",
        "/catalog/supplier",
    ):
        get(path)
    for variant in BOARD_CHECKS:
        get(f"/overview/findings?{variant}")
    for r in answers["/restaurants"]:
        get(f"/overview/restaurants/{r['code']}")
    findings = list(answers["/findings"])
    if hq:
        get("/overview/restaurants")
        get("/checks")
        get("/checks?status=proposed")
        for p in PRESETS:
            get(f"/overview/network?preset={p}")
            get(f"/reports/head?preset={p}")
        for status in ("pending", "confirmed", "rejected"):
            findings += get(f"/findings?review={status}") or []
        for c in answers.get("/checks", []):
            get(f"/checks/{c['id']}")
    seen = set()
    for f in findings:
        if f["id"] in seen:
            continue
        seen.add(f["id"])
        get(f"/findings/{f['id']}")
        if hq:
            get(f"/findings/{f['id']}/verification")
            if f["restaurant_id"] and f["review_status"] in (None, "confirmed"):
                get(f"/checks/draft?finding_id={f['id']}")
    chat: dict[str, Any] = {}
    questions = [*answers["/chat/suggestions"], "Сравни с другими ресторанами", "Что еще?"]
    for q in questions:
        chat[q] = client.post("/api/chat", headers=headers, json={"question": q}).json()
    for f in answers["/findings"]:
        for q in ("Почему так получилось?", "Что мне сделать?", "Сколько это в рублях за год?"):
            chat[f"{f['id']}|{q}"] = client.post(
                "/api/chat", headers=headers, json={"question": q, "finding_id": f["id"]}
            ).json()
    return {"me": me, "answers": answers, "chat": chat}


def main() -> None:
    app.dependency_overrides[get_today] = lambda: DEMO_TODAY
    try:
        with TestClient(app) as client:
            users = {email: record(client, email) for email in USERS}
            snapshot = {
                "recorded_for": DEMO_TODAY.isoformat(),
                "recorded_on": date.today().isoformat(),
                "password": PASSWORD,
                "users": users,
            }
    finally:
        app.dependency_overrides.pop(get_today, None)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    OUT.write_text(text, encoding="utf-8")
    calls = sum(len(u["answers"]) + len(u["chat"]) for u in users.values())
    print(f"{calls} answers → {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
