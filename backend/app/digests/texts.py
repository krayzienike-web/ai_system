"""The digest's texts by rules: what the reader sees when the model is off or its text did not pass the check.

Built only from the digest's input, so every figure is the code's.
"""

from typing import Any

from app.core import words

TASKS = ("задача", "задачи", "задач")


def headline(d: dict[str, Any]) -> str:
    """«Главное за неделю» in two or three sentences."""
    parts = []
    table = d["on_table"]
    if table["total"] and table["total"] != "0 ₽":
        parts.append(
            f"На столе {table['total']} в месяц: потери {table['losses']}, потенциал {table['potential']}."
        )
    if d["problems"]:
        top = d["problems"][0]
        parts.append(f"Главное — «{top['title']}»: {top['effect_per_month']} в месяц.")
    elif d["opportunities"]:
        top = d["opportunities"][0]
        parts.append(f"Главная возможность — «{top['title']}»: {top['effect_per_month']} в месяц.")
    else:
        parts.append("Открытых проблем с оценкой в рублях нет.")
    bad = [p["title"] for p in d["processes"] if p["status"] == "critical"]
    if bad:
        parts.append("Процессы в зоне риска: " + ", ".join(f"«{t}»" for t in bad) + ".")
    done = d["improved"]["tasks_done"]
    if done:
        one = done % 10 == 1 and done % 100 != 11  # «выполнена 21 задача», as «1 задача»
        parts.append(f"За неделю {'выполнена' if one else 'выполнено'} {words.plural(done, TASKS)}.")
    return " ".join(parts)


def item(i: dict[str, Any]) -> str:
    return str(i.get("summary") or i.get("headline") or i["title"])


def by_rules(d: dict[str, Any]) -> dict[str, Any]:
    items = d["problems"] + d["opportunities"] + d["risks"]
    return {"headline": headline(d), "items": {i["finding_id"]: item(i) for i in items}}
