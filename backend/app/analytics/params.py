"""Engine parameters that are not the network's norms (those live in app/norms and are set by HQ).

Every value here is documented in docs/12-analytics-engine.md; changing one is a change of the engine's
logic and goes through that document (and the project workspace) first.
"""

from decimal import Decimal

# M1 — recipe execution
M1_MATERIALITY_RUB_MONTH = Decimal(3000)  # smaller losses are not worth a director's attention
M1_Z = Decimal(2)  # how far from the network a restaurant must be (robust z-score)
M1_Z_FLOOR = Decimal("0.005")  # 0.5 p.p.: the smallest spread the z-score assumes
NETWORK_Z_MIN_RESTAURANTS = 8  # below this the network is too small for a z-score (pilot of 3)
M1_NET_SHARE = Decimal("0.75")  # share of restaurants over the allowance → the recipe, not the kitchens
M1_NET_EXCESS = Decimal("0.02")  # … and the median is at least 2 p.p. over the allowance
M1_MIN_THEORY_DAYS = 14  # a period between counts shorter than this is not judged
