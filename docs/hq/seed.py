"""Rows of the project HQ (docs/hq/hq.html) from docs/ — the source of truth — and params.py: batches of ArtifactData
writes, 50 per file. Run from backend/: `uv run python ../docs/hq/seed.py <out_dir>`."""
import json, re, subprocess, sys
from pathlib import Path
from decimal import Decimal
ROOT = Path("/home/user/ai_system"); OUT = Path(sys.argv[1])
sys.path.insert(0, str(ROOT / "backend"))
from app.analytics.params import DEFS, DEFAULT
writes = []
def put(coll, doc_id, data): writes.append({"op": "set", "collection": coll, "doc_id": doc_id, "data": data})
def cells(line): return [c.strip() for c in line.strip().strip("|").split("|")]
def clean(t): return re.sub(r"\*\*|`", "", re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t))
# questions
oq = (ROOT / "docs/open-questions.md").read_text()
open_part, _, closed_part = oq.partition("## Закрытые")
for line in open_part.splitlines():
    if re.match(r"\| Q\d+ ", line):
        c = cells(line)
        put("questions", c[0], {"num": int(c[0][1:]), "question": clean(c[1]), "why": clean(c[2]), "stage": clean(c[3]),
            "assumption": clean(c[4]), "status": "open", "answer": "", "resolution": ""})
for line in closed_part.splitlines():
    if re.match(r"\| Q\d+ ", line):
        c = cells(line)
        put("questions", c[0], {"num": int(c[0][1:]), "question": clean(c[1]), "why": "", "stage": "",
            "assumption": "", "status": "closed", "answer": "", "resolution": clean(c[2]), "closed_on": clean(c[3]) if len(c) > 3 else ""})
# stages
road = (ROOT / "docs/06-roadmap.md").read_text()
order = 0
for line in road.splitlines():
    m = re.match(r"\| \*\*([\d.]+)\. ([^*]+)\*\* \| (.*)", line)
    if m:
        c = cells(line); order += 1; n = m.group(1)
        status = "done" if float(n) <= 11 or n == "12" else "planned"
        note = ""
        if n == "8":
            status, note = "blocked", "Стенд и боевая конфигурация готовы. Ждем реальные выгрузки пилота (Q5) и ключ Claude API (Q12)"
        if n == "12": note = "Сделано 18.11.2026: итоги инвентаризации и цены меню после роста закупок"
        put("stages", f"s{order:02d}", {"order": order, "num": n, "title": m.group(2).strip(), "content": clean(c[1]),
            "criterion": clean(c[2]), "status": status, "note": note})
# ideas: backlog of docs/07
seven = (ROOT / "docs/07-risks-questions-ideas.md").read_text()
sec = seven[seven.index("## Идеи, как усилить MVP"):]
i = 0
for m in re.finditer(r"^(\d+)\. \*\*([^*]+)\*\*(.*?)(?=^\d+\. \*\*|^- \*\*|^## |\Z)", sec, re.M | re.S):
    i += 1
    body = clean(" ".join(m.group(3).split()))
    group = "agents" if m.start() > sec.index("## ИИ-агенты") else "mvp"
    done = "сделано" in (m.group(2) + body).lower() or f"{group}-{m.group(1)}" in {"mvp-1", "agents-1", "agents-7", "agents-9"}
    put("ideas", f"{group}-{m.group(1)}", {"order": i, "group": group, "title": m.group(2).strip(" ."), "text": body.lstrip(".— "),
        "source": "dev", "status": "done" if done else "backlog", "resolution": ""})
for m in re.finditer(r"^- \*\*([^*]+)\*\*(.*?)(?=^- \*\*|^## |\Z)", sec[:sec.index("## ИИ-агенты")], re.M | re.S):
    i += 1
    put("ideas", f"mvp-x{i}", {"order": i, "group": "mvp", "title": m.group(1).strip(" ."), "text": clean(" ".join(m.group(2).split())).lstrip(". "),
        "source": "dev", "status": "backlog", "resolution": ""})
# engine modules
eng = (ROOT / "docs/12-analytics-engine.md").read_text()
for k, m in enumerate(re.finditer(r"^## (M\d[^\n]*)\n(.*?)(?=^## |\Z)", eng, re.M | re.S)):
    head = m.group(1); paras = [p for p in m.group(2).split("\n\n") if p.strip() and not p.lstrip().startswith(("|", "```", "#"))]
    put("engine", f"e{k:02d}", {"order": k, "title": head, "text": clean(" ".join(paras[0].split()))[:900] if paras else ""})
# params
for k, d in enumerate(DEFS):
    v = d.shown(getattr(DEFAULT, d.key))
    put("engine_params", d.key, {"order": k, "module": d.module, "title": d.title, "unit": d.unit, "meaning": d.meaning,
        "low": float(d.low), "high": float(d.high), "value": float(v), "proposed": None, "status": "applied"})
# log: recent commits
logs = subprocess.run(["git", "-C", str(ROOT), "log", "--since=2026-11-09", "--format=%ad|%s", "--date=short"], capture_output=True, text=True).stdout
for k, line in enumerate(reversed(logs.strip().splitlines())):
    day, subj = line.split("|", 1)
    put("log", f"l{k:03d}", {"order": k, "date": day, "text": subj})
put("log", "l900", {"order": 900, "date": "2026-11-18", "text": "Этап 12: агенты «Итоги инвентаризации» и «Цены меню после роста закупок». Новый штаб проекта: прежний не открывается с текущего аккаунта"})
OUT.mkdir(parents=True, exist_ok=True)
for n in range(0, len(writes), 50):
    (OUT / f"batch{n//50:02d}.json").write_text(json.dumps(writes[n:n+50], ensure_ascii=False))
from collections import Counter
print(Counter(w["collection"] for w in writes), len(writes))
