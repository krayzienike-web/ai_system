"""`uv run python -m app.ai.evals [--suite chat|hypotheses|digest]` — the assistant's evals on the demo
network with the real model.

Before: the demo network (`app.cli seed-demo`, `load-demo`), FAI_AI_PROVIDER=claude, ANTHROPIC_API_KEY; for
`hypotheses` also its answer key: `app.cli generate-demo --out demo-data` (then `--anomalies` finds it).
Every call is a real model call (and is logged in ai_runs): chat — about 40 questions, a few rounds each;
hypotheses — 16 findings, one or two calls each; digest — the latest digest of the network and of every
restaurant (`load-demo` builds them), one or two calls each.
"""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.ai import evals as chat_eval
from app.ai.evals import digest, hypotheses, load_cases, run, world_from
from app.ai.gateway import Gateway, get_model
from app.core.config import get_settings
from app.tenancy.context import tool_session


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=["chat", "hypotheses", "digest"], default="chat")
    parser.add_argument("--anomalies", default="demo-data/anomalies.json", help="the demo's answer key")
    parser.add_argument("--director", default="director1@demo.local")
    parser.add_argument("--hq", default="admin@demo.local")
    parser.add_argument("--only", nargs="*", help="case ids")
    parser.add_argument("--out", help="write the full report as JSON here")
    args = parser.parse_args()
    model = get_model()
    if model is None:
        raise SystemExit("The model is off: set FAI_AI_PROVIDER=claude and ANTHROPIC_API_KEY")
    gateway = Gateway(model, per_user_day=10_000)
    owner = create_engine(get_settings().migrations_database_url)
    with Session(owner) as session:
        world = world_from(session, director_email=args.director, hq_email=args.hq)
        anomalies = (
            json.loads(Path(args.anomalies).read_text(encoding="utf-8"))["anomalies"]
            if args.suite == "hypotheses"
            else []
        )
        planted = hypotheses.cases(session, world.people["hq"].tenant_id, anomalies)
        digests = digest.cases(session, world.people["hq"].tenant_id) if args.suite == "digest" else []
    owner.dispose()
    report: chat_eval.Report | hypotheses.Report | digest.Report
    if args.suite == "chat":
        cases = [c for c in load_cases() if not args.only or c["id"] in args.only]
        report = run(gateway, world, world.today, cases)
    elif args.suite == "digest":
        hq = world.people["hq"]
        with tool_session(hq.user_id, hq.tenant_id) as (_, ctx):
            pass
        report = digest.run(gateway, ctx, [c for c in digests if not args.only or c.scope in args.only])
    else:
        hq = world.people["hq"]
        with tool_session(hq.user_id, hq.tenant_id) as (_, ctx):
            pass
        report = hypotheses.run(
            gateway, ctx, world.today, [c for c in planted if not args.only or c.anomaly in args.only]
        )
    print(report.summary())
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump([asdict(o) for o in report.outcomes], f, ensure_ascii=False, indent=2)
    sys.exit(0 if report.passed else 1)


if __name__ == "__main__":
    main()
