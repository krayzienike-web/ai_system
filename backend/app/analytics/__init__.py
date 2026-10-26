"""Analytics engine: deterministic metrics and detectors (docs/02-analytics-spec.md, docs/12).

Pure functions over `Facts`; only `facts.load_facts` and `engine` touch the database. Never imports `ai`.
"""
