"""Vendored subset of the `stk` stock-analysis engine.

Only the pure-analysis modules are included (analysis, nasdaq, indicators,
history, universe, net) — enough to run the NASDAQ-100 scorecard. The CLI, Excel
report and Yahoo `quotes` modules from the upstream project are intentionally
left out (they pull in `rich`/`openpyxl` and are not used server-side).

Upstream source: /Users/sanketsarmalkar/Desktop/coding/stk_h
"""

__version__ = "0.1.0"
