"""`uv run python -m app.ai.evals` — the chat's eval on the demo network with the real model.

Before: the demo network (`app.cli seed-demo`, `load-demo`), FAI_AI_PROVIDER=claude, ANTHROPIC_API_KEY.
Every call is a real model call (and is logged in ai_runs): about 40 questions, a few rounds each.
"""

import argparse
import json
import sys
from dataclasses import asdict

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.ai.evals import load_cases, run, world_from
from app.ai.gateway import Gateway, get_model
from app.core.config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--director", default="director1@demo.local")
    parser.add_argument("--hq", default="admin@demo.local")
    parser.add_argument("--only", nargs="*", help="case ids")
    parser.add_argument("--out", help="write the full report as JSON here")
    args = parser.parse_args()
    model = get_model()
    if model is None:
        raise SystemExit("The model is off: set FAI_AI_PROVIDER=claude and ANTHROPIC_API_KEY")
    owner = create_engine(get_settings().migrations_database_url)
    with Session(owner) as session:
        world = world_from(session, director_email=args.director, hq_email=args.hq)
    owner.dispose()
    cases = [c for c in load_cases() if not args.only or c["id"] in args.only]
    report = run(Gateway(model, per_user_day=10_000), world, world.today, cases)
    print(report.summary())
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump([asdict(o) for o in report.outcomes], f, ensure_ascii=False, indent=2)
    sys.exit(0 if report.passed else 1)


if __name__ == "__main__":
    main()
