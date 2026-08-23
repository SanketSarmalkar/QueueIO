"""Daily NASDAQ stock-scorecard pipeline.

Runs the vendored `stk` analysis engine over the NASDAQ-100, turns each
``Analysis`` row into a plain dict, and stores a single dated snapshot document
in MongoDB (`stock_results`). The dashboard "Stocks" tab reads the most recent
snapshot back out — the heavy ~2.5 min fetch never happens during a page load.

Triggered every morning by a CronJob (endpoint `/tasks/stocks_refresh/`), or
manually via the Command Center "Run now" button.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime, timezone

from ..stk_engine import nasdaq
from ..stk_engine.analysis import analyse_universe
from ..stk_engine.universe import get_universe

logger = logging.getLogger(__name__)

# Where daily snapshots live in MongoDB.
STOCK_COLLECTION = "stock_results"


def run_stock_analysis(universe: str = "nasdaq100", *, workers: int = 6,
                       timeout: float = 12.0, with_fundamentals: bool = True,
                       force: bool = False, min_interval_hours: int = 12) -> dict:
    """Fetch + score ``universe`` and insert one snapshot doc into MongoDB.

    Idempotent by default: if a good snapshot already exists within the last
    ``min_interval_hours`` (default 20h, just under the daily cadence), the run
    is skipped. This keeps container restarts/deploys — which re-run the
    scheduler — from firing a wasteful ~2.5 min fetch and duplicating the daily
    snapshot, while still letting the daily 24h-apart cron run through. Pass
    ``force=True`` (or `?force=1` on the endpoint) to override.

    Returns a small summary dict (counts + how many symbols scored/failed).
    """
    from datetime import timedelta
    # Imported lazily so this module is importable even if Mongo env vars are
    # missing (e.g. during migrations / collectstatic).
    from ..config import MONGO_DB

    collection = MONGO_DB[STOCK_COLLECTION]

    if not force:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=min_interval_hours)
        recent = collection.find_one(
            {"universe": universe, "scored_count": {"$gt": 0}, "createdat": {"$gte": cutoff}},
            {"_id": 0, "generated": 1},
            sort=[("createdat", -1)],
        )
        if recent:
            logger.info("stock pipeline: fresh snapshot exists (%s) — skipping (use force=True to override)",
                        recent.get("generated"))
            return {"status": "skipped", "reason": "recent snapshot exists",
                    "generated": recent.get("generated")}

    symbols = get_universe(universe)
    logger.info("stock pipeline: analysing %d symbols (%s)", len(symbols), universe)

    rows = analyse_universe(
        symbols,
        history_fn=lambda s, timeout: nasdaq.fetch_history(s, timeout=timeout),
        index_fn=lambda: nasdaq.fetch_index_history(timeout=timeout),
        fundamentals_fn=lambda price_by: nasdaq.fetch_fundamentals(
            price_by, timeout=timeout, workers=workers
        ),
        with_fundamentals=with_fundamentals,
        workers=workers,
        timeout=timeout,
    )

    scored = [asdict(a) for a in rows if a.error is None]
    failed = [{"symbol": a.symbol, "error": a.error} for a in rows if a.error is not None]

    counts = {"bullish": 0, "neutral": 0, "bearish": 0}
    for a in scored:
        sig = (a.get("signal") or "").lower()
        if sig in counts:
            counts[sig] += 1

    now = datetime.now(timezone.utc)
    doc = {
        "universe": universe,
        "createdat": now,                      # UTC datetime — sortable
        "generated": now.isoformat(),          # ISO string for display
        "counts": counts,
        "scored_count": len(scored),
        "failed_count": len(failed),
        "rows": scored,
        "failed": failed,
    }

    if not scored:
        # Likely rate-limited — don't overwrite a good snapshot with an empty one.
        logger.warning("stock pipeline: no symbols scored (%d failed) — snapshot NOT stored",
                       len(failed))
        return {"status": "warning", "message": "no symbols scored", **counts}

    collection.insert_one(doc)
    logger.info("stock pipeline: stored snapshot — %d scored, %d failed, counts=%s",
                len(scored), len(failed), counts)

    return {
        "status": "success",
        "universe": universe,
        "scored_count": len(scored),
        "failed_count": len(failed),
        **counts,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(run_stock_analysis())
