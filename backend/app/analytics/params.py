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

# M3 — purchase prices
M3_WINDOW_DAYS = 56  # the last 8 weeks of purchases are compared
M3_MIN_RECEIPTS = 2  # fewer purchases of a product in the window: no conclusion
M3_OVERPAY = Decimal("0.05")  # 5 % above the typical price of the network
M3_MATERIALITY_RUB_MONTH = Decimal(3000)
M3_Z = Decimal(2)
M3_Z_FLOOR = Decimal("0.01")  # 1 %: the smallest price spread the z-score assumes
M3_CONTRACT_TOLERANCE = Decimal("0.01")  # rounding in invoices: up to 1 % above the contract is not a finding
M3_NET_WINDOW_DAYS = 28  # network-wide growth: the last 4 weeks …
M3_NET_COMPARE_DAYS = 91  # … against the same 4 weeks a quarter earlier
M3_NET_GROWTH = Decimal("0.10")  # 10 % more for the whole network

# M2 — food cost of dishes
M2_WINDOW_DAYS = 28  # current ingredient prices: the network's purchases over the last 4 weeks
M2_COMPARE_DAYS = 91  # «before»: the same window a quarter earlier
M2_KEEP = Decimal("0.5")  # conservative: half of the extra margin survives guests ordering less
M2_MATERIALITY_RUB_MONTH = Decimal(3000)
M2_PRICE_STEP = Decimal(10)  # suggested menu prices are rounded up to 10 ₽
