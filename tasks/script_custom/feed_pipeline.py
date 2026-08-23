"""Generic scheduled-LLM feed pipeline.

Runs a `DashboardFeed`'s prompt through Gemini and stores the latest response in
MongoDB (`dashboard_feeds`). The dashboard injects that latest doc server-side and
auto-renders it as a tab (markdown or table). Triggered by a CronJob (endpoint
`/tasks/feed/<key>/`) or manually via the Command Center "Run now".
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

FEED_COLLECTION = "dashboard_feeds"


def _parse_json_rows(text: str):
    """Best-effort extract a JSON array of objects from an LLM response.

    Handles ```json fenced blocks and leading/trailing prose. Returns a list of
    dicts (possibly empty) plus the column order discovered from the first row.
    """
    cleaned = text.strip()
    # Strip a ```json ... ``` (or ``` ... ```) fence if present.
    fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()
    else:
        # Otherwise grab the outermost [ ... ] array.
        start, end = cleaned.find("["), cleaned.rfind("]")
        if start != -1 and end != -1 and end > start:
            cleaned = cleaned[start:end + 1]
    try:
        data = json.loads(cleaned)
    except Exception:
        return [], []
    if not isinstance(data, list):
        return [], []
    rows = [d for d in data if isinstance(d, dict)]
    columns = list(rows[0].keys()) if rows else []
    return rows, columns


def run_feed(key: str, *, force: bool = False, min_interval_hours: int = 12) -> dict:
    """Run the feed identified by ``key`` and store its latest response.

    Idempotent by default (skips if a doc exists within ``min_interval_hours``),
    so container restarts don't re-run every feed. Pass ``force=True`` to override.
    """
    from tasks.models import DashboardFeed
    from ..config import GEN_AI_CLIENT, MONGO_DB, get_global_setting

    feed = DashboardFeed.objects.filter(key=key, is_active=True).first()
    if feed is None:
        return {"status": "error", "message": f"no active feed '{key}'"}

    collection = MONGO_DB[FEED_COLLECTION]

    if not force:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=min_interval_hours)
        if collection.find_one({"feed_key": key, "createdat": {"$gte": cutoff}}):
            logger.info("feed '%s': fresh doc exists — skipping (force=True to override)", key)
            return {"status": "skipped", "reason": "recent doc exists"}

    model = feed.ai_model or get_global_setting("AI_MODEL", os.getenv("AI_MODEL", "gemini-2.0-flash"))
    logger.info("feed '%s': generating with model %s", key, model)

    try:
        response = GEN_AI_CLIENT.models.generate_content(model=model, contents=feed.prompt)
        text = (response.text or "").strip()
    except Exception as e:
        logger.error("feed '%s': LLM call failed: %s", key, e)
        return {"status": "error", "message": str(e)}

    if not text:
        return {"status": "error", "message": "empty LLM response"}

    now = datetime.now(timezone.utc)
    doc = {
        "feed_key": key,
        "title": feed.title,
        "icon": feed.icon,
        "render_type": feed.render_type,
        "model": model,
        "generated": now.isoformat(),
        "createdat": now,
    }
    if feed.render_type == DashboardFeed.RENDER_TABLE:
        rows, columns = _parse_json_rows(text)
        doc["rows"] = rows
        doc["columns"] = columns
        doc["raw"] = text  # keep the raw response for debugging / fallback
    else:
        doc["content"] = text

    collection.insert_one(doc)
    logger.info("feed '%s': stored (%s, %d chars)", key, feed.render_type, len(text))
    return {"status": "success", "feed_key": key, "render_type": feed.render_type,
            "generated": doc["generated"]}


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    print(run_feed(sys.argv[1] if len(sys.argv) > 1 else "ai_brief", force=True))
