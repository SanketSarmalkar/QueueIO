from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout
from django.contrib.auth.forms import UserCreationForm
from django.contrib import messages
from django.http import JsonResponse
from datetime import datetime
from google import genai
import os
import json
import time
from bson import ObjectId
from django.utils.timezone import now as tz_now

import threading
from tasks.models import TaskConfiguration, GlobalSetting, CronJob
from django.contrib.auth.decorators import user_passes_test

# ── Intel Chat rate limiting (per-user, in-memory) ────────────────────────────
_CHAT_RATE: dict[int, list[float]] = {}
_CHAT_LIMIT = 20       # max requests
_CHAT_WINDOW = 3600    # per hour (seconds)
_CHAT_RATE_LOCK = threading.Lock()

def _check_chat_rate(user_id: int) -> bool:
    now = time.time()
    with _CHAT_RATE_LOCK:
        timestamps = [t for t in _CHAT_RATE.get(user_id, []) if now - t < _CHAT_WINDOW]
        if len(timestamps) >= _CHAT_LIMIT:
            return False
        timestamps.append(now)
        _CHAT_RATE[user_id] = timestamps
    return True

KNOWN_SETTINGS = [
    {'key': 'YOUTUBE_PLAYLIST_IDS',  'description': 'Comma-separated YouTube playlist IDs to monitor', 'env_key': 'YOUTUBE_PLAYLIST_IDS'},
    {'key': 'PLAYLIST_FETCH_LIMIT',  'description': 'Max recent videos to fetch per playlist per pipeline run', 'env_key': 'PLAYLIST_FETCH_LIMIT'},
    {'key': 'AI_MODEL',              'description': 'Gemini model for LLM inference (e.g. gemini-2.0-flash)', 'env_key': 'AI_MODEL'},
    {'key': 'EXECUTOR_WORKERS',      'description': 'Concurrent thread pool workers for video processing', 'env_key': 'EXECUTOR_WORKERS'},
    {'key': 'INBETWEEN_TASK_SLEEP',  'description': 'Seconds to pause between thread pool batches', 'env_key': 'INBETWEEN_TASK_SLEEP'},
    {'key': 'EXTRA_DOCUMENT_ARGS',   'description': 'JSON object of extra fields injected into every MongoDB document', 'env_key': 'EXTRA_DOCUMENT_ARGS'},
]
KNOWN_KEYS = {s['key'] for s in KNOWN_SETTINGS}


def custom_404(request, exception):
    return render(request, '404.html', status=404)

@login_required
def dashboard(request):
    is_authorized = request.user.groups.filter(name__in=['Analyst', 'Supervisor']).exists()
    if not is_authorized:
        return render(request, 'access_denied.html')

    collection = get_db_collection()

    # Stack counts — one aggregation, no full scan
    # $ifNull handles old docs that stored the ID in "playlist" instead of "playlist_id"
    stack_pipeline = [
        {"$group": {
            "_id": {"$ifNull": ["$playlist_id", "$playlist"]},
            "count": {"$sum": 1},
            "title": {"$first": "$playlist_title"},
            "thumbnail_key": {"$first": "$key"},
        }},
        {"$sort": {"count": -1}},
    ]
    stacks_json = [
        {
            "id": s["_id"] or "unassigned",
            "count": s["count"],
            "title": s.get("title") or "General Archive",
            "thumbnail_key": s.get("thumbnail_key") or "",
        }
        for s in collection.aggregate(stack_pipeline)
    ]

    total = collection.estimated_document_count()
    records = list(collection.find({}, {'value': 0, 'embedding': 0}).sort('createdat', -1).limit(_PAGE_SIZE))
    formatted_items = [_format_record(r) for r in records]

    tasks_list = list(TaskConfiguration.objects.all().values(
        'id', 'task_key', 'display_name', 'prompt_template', 'target_collection', 'is_active'
    ))

    # Latest NASDAQ stock scorecard snapshot — injected server-side and rendered
    # inline in the Stocks tab, the same way `stacks_json` feeds the Stacks view.
    try:
        from tasks.config import MONGO_DB
        stocks_json = MONGO_DB["stock_results"].find_one(
            {"scored_count": {"$gt": 0}},
            {"_id": 0, "failed": 0, "createdat": 0},
            sort=[("createdat", -1)],
        ) or {}
    except Exception:
        stocks_json = {}

    # Generic DashboardFeeds — the "Feeds" tab shows a card per feed; drilling into
    # one reveals a tab per run (each scheduled run is stored as a new snapshot).
    feeds_json = []
    try:
        from tasks.models import DashboardFeed
        from tasks.config import MONGO_DB as _MDB
        feed_coll = _MDB["dashboard_feeds"]
        for f in DashboardFeed.objects.filter(is_active=True).order_by('title'):
            runs = list(feed_coll.find(
                {"feed_key": f.key},
                {"_id": 0, "createdat": 0, "raw": 0, "feed_key": 0, "title": 0, "icon": 0},
                sort=[("createdat", -1)],
            ).limit(_FEED_HISTORY_LIMIT))
            feeds_json.append({
                "key": f.key,
                "title": f.title,
                "icon": f.icon or "fa-newspaper",
                "render_type": f.render_type,
                "runs": runs,  # newest first; empty until the feed has run once
            })
    except Exception:
        feeds_json = []

    return render(request, 'dashboard.html', {
        'items_raw': formatted_items,
        'latest_id': formatted_items[0]['id'] if formatted_items else '',
        'tasks_json': tasks_list,
        'stacks_json': stacks_json,
        'stocks_json': stocks_json,
        'feeds_json': feeds_json,
        'total_count': total,
        'has_more': 'true' if total > _PAGE_SIZE else 'false',
        'next_offset': _PAGE_SIZE,
    })


@login_required
def get_more_records(request):
    offset = int(request.GET.get('offset', _PAGE_SIZE))
    playlist_id = request.GET.get('playlist_id', '').strip()
    collection = get_db_collection()

    if playlist_id:
        _ensure_playlist_index(collection)
        # Match both new-style (playlist_id) and old-style (playlist) field names
        mongo_filter = {'$or': [{'playlist_id': playlist_id}, {'playlist': playlist_id}]}
        total = collection.count_documents(mongo_filter)
        records = list(collection.find(mongo_filter, {'value': 0, 'embedding': 0}).sort('createdat', -1).skip(offset).limit(_PAGE_SIZE))
    else:
        mongo_filter = {}
        total = collection.estimated_document_count()
        records = list(collection.find(mongo_filter, {'value': 0, 'embedding': 0}).sort('createdat', -1).skip(offset).limit(_PAGE_SIZE))

    return JsonResponse({
        'items': [_format_record(r) for r in records],
        'has_more': offset + _PAGE_SIZE < total,
        'next_offset': offset + _PAGE_SIZE,
        'total': total,
    })

@login_required
def list_bookmarks(request):
    from records.models import Bookmark
    ids = list(Bookmark.objects.filter(user=request.user).values_list('report_id', flat=True))
    return JsonResponse({'ids': ids})


@login_required
def toggle_bookmark(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    from records.models import Bookmark
    data = json.loads(request.body)
    report_id = data.get('report_id', '').strip()
    title = data.get('title', '')
    if not report_id:
        return JsonResponse({'error': 'report_id required'}, status=400)
    existing = Bookmark.objects.filter(user=request.user, report_id=report_id).first()
    if existing:
        existing.delete()
        return JsonResponse({'bookmarked': False})
    Bookmark.objects.create(user=request.user, report_id=report_id, title=title)
    return JsonResponse({'bookmarked': True})


@login_required
def get_related_reports(request, report_id):
    try:
        collection = get_db_collection()
        doc = collection.find_one({"_id": ObjectId(report_id)}, {"embedding": 1})
        if not doc or not doc.get("embedding"):
            return JsonResponse({"items": []})

        pipeline = [
            {
                "$vectorSearch": {
                    "index": "vector_index",
                    "path": "embedding",
                    "queryVector": doc["embedding"],
                    "numCandidates": 50,
                    "limit": 6,
                }
            },
            {
                "$project": {
                    "a": 1, "category": 1, "key": 1,
                    "createdat": 1, "playlist_id": 1, "playlist_title": 1,
                }
            },
        ]
        results = list(collection.aggregate(pipeline))
        # exclude the source document itself
        results = [r for r in results if str(r["_id"]) != report_id][:4]
        return JsonResponse({"items": [_format_record(r) for r in results]})
    except Exception:
        return JsonResponse({"items": []})


@login_required
def search_records(request):
    q = request.GET.get('q', '').strip()
    if len(q) < 3:
        return JsonResponse({'items': []})

    collection = get_db_collection()
    _ensure_text_index(collection)

    try:
        cursor = collection.find(
            {"$text": {"$search": q}},
            {"value": 0, "embedding": 0},
        ).limit(50)
        items = [_format_record(r) for r in cursor]
    except Exception:
        # Text index not ready yet — fall back to title-only regex
        cursor = collection.find(
            {"a": {"$regex": q, "$options": "i"}},
            {"value": 0, "embedding": 0},
        ).limit(50)
        items = [_format_record(r) for r in cursor]

    return JsonResponse({'items': items, 'query': q})


def logout_view(request):
    logout(request)
    return redirect('login')

def signup_view(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.is_active = False 
            user.save()
            
            messages.success(request, "ACCESS REQUEST SENT. AWAITING SUPERVISOR AUTHORIZATION.")
            return redirect('login')
    else:
        form = UserCreationForm()
    return render(request, 'signup.html', {'form': form})

@login_required
def get_report_content(request, report_id):
    collection = get_db_collection()
    report = collection.find_one(
        {"_id": ObjectId(report_id)},
        {"value": 1, "entities": 1, "a": 1, "category": 1, "key": 1, "createdat": 1, "playlist_id": 1, "playlist_title": 1}
    )
    raw_entities = report.get('entities', '{}')
    if isinstance(raw_entities, str):
        try:
            entities_data = json.loads(raw_entities.strip())
        except Exception:
            entities_data = {"people": [], "locations": [], "organizations": []}
    else:
        entities_data = raw_entities

    created_at = report.get('createdat')
    date_display, time_display = 'N/A', 'N/A'
    if created_at:
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        if hasattr(created_at, 'strftime'):
            date_display = created_at.strftime('%b %d, %Y')
            time_display = created_at.strftime('%I:%M %p')

    return JsonResponse({
        "value": report.get('value', 'No content found.'),
        "entities": entities_data,
        "title": (report.get('a') or 'Untitled Record').split('|')[0].strip(),
        "category": report.get('category', ''),
        "key": report.get('key', ''),
        "date_display": date_display,
        "time_display": time_display,
        "playlist_id": report.get('playlist_id') or report.get('playlist') or None,
        "playlist_title": report.get('playlist_title') or '',
    })

_PAGE_SIZE = 50
_FEED_HISTORY_LIMIT = 15  # how many recent runs (tabs) to load per dashboard feed
_TEXT_INDEX_ENSURED = False
_PLAYLIST_INDEX_ENSURED = False
_ENTITY_STATS_CACHE = None
_ENTITY_STATS_TS = None

# Free-tier daily request limits per model family
_FREE_TIER_RPD = 1500
_FREE_TIER_TPD = 1_000_000

def _log_api_usage(model, request_type, usage_metadata, source='intel_chat'):
    try:
        from records.models import ApiUsageLog
        ApiUsageLog.objects.create(
            date=tz_now().date(),
            model=model,
            request_type=request_type,
            prompt_tokens=getattr(usage_metadata, 'prompt_token_count', 0) or 0,
            output_tokens=getattr(usage_metadata, 'candidates_token_count', 0) or 0,
            total_tokens=getattr(usage_metadata, 'total_token_count', 0) or 0,
            source=source,
        )
    except Exception:
        pass

def get_db_collection():
    from tasks.config import MONGO_DB
    return MONGO_DB["mass_records"]

def _ensure_text_index(collection):
    global _TEXT_INDEX_ENSURED
    if _TEXT_INDEX_ENSURED:
        return
    try:
        collection.create_index(
            [("a", "text"), ("value", "text")],
            weights={"a": 10, "value": 1},
            background=True,
            name="full_text_search",
        )
    except Exception:
        pass
    _TEXT_INDEX_ENSURED = True

def _ensure_playlist_index(collection):
    global _PLAYLIST_INDEX_ENSURED
    if _PLAYLIST_INDEX_ENSURED:
        return
    try:
        collection.create_index([("playlist_id", 1)], background=True, name="playlist_id_idx")
        collection.create_index([("playlist", 1)], background=True, name="playlist_idx")
    except Exception:
        pass
    _PLAYLIST_INDEX_ENSURED = True

@login_required
def get_entity_stats(request):
    global _ENTITY_STATS_CACHE, _ENTITY_STATS_TS
    import time
    now = time.time()
    if _ENTITY_STATS_CACHE is not None and (now - _ENTITY_STATS_TS) < 600:
        return JsonResponse(_ENTITY_STATS_CACHE)

    collection = get_db_collection()

    # ── Entity counts ──────────────────────────────────────────────────────────
    counts = {"people": {}, "locations": {}, "organizations": {}}
    for doc in collection.find({"entities": {"$exists": True}}, {"entities": 1}):
        raw = doc.get("entities", {})
        if isinstance(raw, str):
            try:
                raw = json.loads(raw.strip())
            except Exception:
                continue
        for cat in counts:
            for name in raw.get(cat, []):
                name = name.strip()
                if name:
                    counts[cat][name] = counts[cat].get(name, 0) + 1

    result = {}
    for cat, freq in counts.items():
        top = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:15]
        result[cat] = [{"name": n, "count": c} for n, c in top]

    # ── Volume over time (last 12 months) ──────────────────────────────────────
    monthly_pipeline = [
        {"$match": {"createdat": {"$exists": True, "$type": "date"}}},
        {"$group": {
            "_id": {"year": {"$year": "$createdat"}, "month": {"$month": "$createdat"}},
            "count": {"$sum": 1},
        }},
        {"$sort": {"_id.year": 1, "_id.month": 1}},
        {"$limit": 12},
    ]
    _MONTH_NAMES = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    result["monthly_volume"] = [
        {"month": f"{_MONTH_NAMES[r['_id']['month']-1]} {r['_id']['year']}", "count": r["count"]}
        for r in collection.aggregate(monthly_pipeline)
    ]

    # ── Category breakdown ─────────────────────────────────────────────────────
    cat_pipeline = [
        {"$group": {"_id": "$category", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    result["categories"] = [
        {"name": r["_id"] or "unknown", "count": r["count"]}
        for r in collection.aggregate(cat_pipeline)
    ]

    # ── Playlist distribution ──────────────────────────────────────────────────
    playlist_pipeline = [
        {"$group": {
            "_id": "$playlist_title",
            "count": {"$sum": 1},
        }},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]
    result["playlists"] = [
        {"name": r["_id"] or "General Archive", "count": r["count"]}
        for r in collection.aggregate(playlist_pipeline)
    ]

    # ── Archive health ─────────────────────────────────────────────────────────
    total = collection.estimated_document_count()
    with_entities = collection.count_documents({"entities": {"$exists": True}})
    with_embeddings = collection.count_documents({"embedding": {"$exists": True}})
    result["health"] = {
        "total": total,
        "with_entities": with_entities,
        "with_embeddings": with_embeddings,
        "entities_pct": round(with_entities / total * 100) if total else 0,
        "embeddings_pct": round(with_embeddings / total * 100) if total else 0,
    }

    _ENTITY_STATS_CACHE = result
    _ENTITY_STATS_TS = now
    return JsonResponse(result)

@login_required
def get_usage_stats(request):
    from records.models import ApiUsageLog
    from django.db.models import Sum, Count
    from datetime import timedelta

    today = tz_now().date()

    # ── Today's totals by request type ────────────────────────────────────────
    today_qs = ApiUsageLog.objects.filter(date=today)
    gen_today = today_qs.filter(request_type='generate').aggregate(
        requests=Count('id'), tokens=Sum('total_tokens'), prompt=Sum('prompt_tokens'), output=Sum('output_tokens')
    )
    embed_today = today_qs.filter(request_type='embed').aggregate(
        requests=Count('id'), tokens=Sum('total_tokens')
    )
    source_breakdown = {}
    for row in today_qs.values('source').annotate(requests=Count('id'), tokens=Sum('total_tokens')):
        source_breakdown[row['source']] = {'requests': row['requests'], 'tokens': row['tokens'] or 0}

    # ── Last 7 days ────────────────────────────────────────────────────────────
    daily = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        agg = ApiUsageLog.objects.filter(date=d).aggregate(requests=Count('id'), tokens=Sum('total_tokens'))
        daily.append({
            'date': d.strftime('%b %d'),
            'requests': agg['requests'] or 0,
            'tokens': agg['tokens'] or 0,
        })

    total_today = (gen_today['requests'] or 0) + (embed_today['requests'] or 0)
    total_tokens_today = (gen_today['tokens'] or 0) + (embed_today['tokens'] or 0)

    return JsonResponse({
        'today': {
            'total_requests': total_today,
            'total_tokens': total_tokens_today,
            'generate_requests': gen_today['requests'] or 0,
            'generate_tokens': gen_today['tokens'] or 0,
            'embed_requests': embed_today['requests'] or 0,
            'embed_tokens': embed_today['tokens'] or 0,
        },
        'source_breakdown': source_breakdown,
        'daily': daily,
        'limits': {
            'rpd': _FREE_TIER_RPD,
            'tpd': _FREE_TIER_TPD,
        },
    })

@login_required
def get_stocks_data(request):
    """Return the most recent NASDAQ stock-scorecard snapshot for the Stocks tab.

    The heavy analysis runs in the daily 9 AM CronJob and is stored in MongoDB
    (`stock_results`); this endpoint just serves the latest snapshot.
    """
    from tasks.config import MONGO_DB

    try:
        collection = MONGO_DB["stock_results"]
        snap = collection.find_one(
            {"scored_count": {"$gt": 0}},
            {"_id": 0, "failed": 0, "createdat": 0},
            sort=[("createdat", -1)],
        )
    except Exception as e:
        return JsonResponse({"error": str(e), "rows": []}, status=200)

    if not snap:
        return JsonResponse({"empty": True, "rows": []})

    return JsonResponse(snap)


def _format_record(item):
    created_at = item.get('createdat')
    date_display = "N/A"
    time_display = "N/A"
    if created_at:
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        if hasattr(created_at, "strftime"):
            date_display = created_at.strftime("%b %d, %Y")
            time_display = created_at.strftime('%I:%M %p')
    return {
        'id': str(item['_id']),
        'category': item.get('category', 'queuei'),
        'key': item.get('key', ''),
        'title': (item.get('a') or 'Untitled Record').split('|')[0].strip(),
        'date_display': date_display,
        'time_display': time_display,
        'playlist_id': item.get('playlist_id') or item.get('playlist') or None,
        'playlist_title': item.get('playlist_title') or item.get('playlist_id') or item.get('playlist') or 'General Archive',
    }

@login_required
def intel_chat_view(request):
    if request.method == "POST":
        if not _check_chat_rate(request.user.id):
            return JsonResponse({'error': 'Rate limit exceeded. Max 20 queries per hour.'}, status=429)
        try:
            data = json.loads(request.body)
            user_query = data.get('query', '').strip()
            history = data.get('history', [])  # [{role: "user"/"ai", text: "..."}]

            from tasks.config import get_global_setting
            ai_model = get_global_setting('AI_MODEL', os.getenv('AI_MODEL', 'gemini-2.0-flash'))

            client = genai.Client(api_key=os.getenv("GEN_AI_API_KEY"))
            collection = get_db_collection()

            query_res = client.models.embed_content(
                model="gemini-embedding-001",
                contents=[user_query]
            )
            query_vector = query_res.embeddings[0].values
            _log_api_usage("gemini-embedding-001", "embed", query_res.usage_metadata)

            pipeline = [
                {
                    "$vectorSearch": {
                        "index": "vector_index",
                        "path": "embedding",
                        "queryVector": query_vector,
                        "numCandidates": 100,
                        "limit": 6
                    }
                },
                {
                    "$project": {
                        "a": 1,
                        "value": 1,
                        "playlist_title": 1,
                        "createdat": 1,
                        "score": {"$meta": "vectorSearchScore"}
                    }
                }
            ]
            context_reports = list(collection.aggregate(pipeline))

            context_text = "\n\n".join([
                f"[SOURCE {i+1}] {r.get('a') or ''} ({r.get('playlist_title') or ''})\n{r.get('value') or ''}"
                for i, r in enumerate(context_reports)
            ])

            history_text = ""
            if history:
                turns = []
                for turn in history[-6:]:  # last 3 exchanges
                    role = "Analyst" if turn.get("role") == "ai" else "Operator"
                    turns.append(f"{role}: {turn.get('text', '')}")
                history_text = "CONVERSATION HISTORY:\n" + "\n\n".join(turns) + "\n\n"

            prompt = f"""You are a Senior Intelligence Analyst with access to a curated archive of reports. \
Answer questions based ONLY on the archive data provided. Be concise and professional. \
If the archive data is insufficient, say so clearly rather than speculating.

{history_text}CURRENT QUERY: {user_query}

ARCHIVE DATA:
{context_text}"""

            llm_res = client.models.generate_content(model=ai_model, contents=prompt)
            _log_api_usage(ai_model, "generate", llm_res.usage_metadata)

            sources = []
            for r in context_reports:
                created = r.get('createdat')
                date_str = ""
                if created and hasattr(created, 'strftime'):
                    date_str = created.strftime("%b %d, %Y")
                sources.append({
                    "id": str(r['_id']),
                    "title": (r.get('a') or 'Untitled').split('|')[0].strip(),
                    "playlist_title": r.get('playlist_title', ''),
                    "date": date_str,
                })

            return JsonResponse({"answer": llm_res.text, "sources": sources})
        except Exception as e:
            return JsonResponse({"answer": f"SYSTEM ERROR: {str(e)}"}, status=500)
    return redirect('dashboard')

def is_supervisor(user):
    return user.groups.filter(name='Supervisor').exists() or user.is_superuser

@login_required
@user_passes_test(is_supervisor)
def command_center_view(request):
    """
    Handles POST requests from the Command Center UI.
    Note: For GET requests, we usually want to stay on the dashboard,
    but if they hit this URL directly, we need to provide the same data.
    """
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            action = data.get('action')
            
            if action == 'create_task':
                if TaskConfiguration.objects.filter(task_key=data['task_key']).exists():
                    return JsonResponse({'status': 'error', 'message': 'Task Key already exists'}, status=400)
                task = TaskConfiguration(task_key=data['task_key'])
            
            elif action == 'update_task':
                task = TaskConfiguration.objects.get(id=data['id'])
            
            elif action == 'delete_task':
                TaskConfiguration.objects.filter(id=data['id']).delete()
                return JsonResponse({'status': 'success'})

            task.display_name = data['display_name']
            task.prompt_template = data['prompt_template']
            task.target_collection = data.get('target_collection', 'mass_records')
            task.is_active = data.get('is_active', True)
            task.save()
            
            return JsonResponse({
                'status': 'success', 
                'task': {
                    'id': task.id,
                    'task_key': task.task_key,
                    'display_name': task.display_name,
                    'prompt_template': task.prompt_template,
                    'target_collection': task.target_collection,
                    'is_active': task.is_active
                }
            })
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    return redirect('dashboard')

@login_required
def get_nexus_graph(request):
    collection = get_db_collection()
    reports = list(collection.find(
        {"entities": {"$exists": True}},
        {"a": 1, "entities": 1}
    ).sort('createdat', -1).limit(500))
    
    nodes = []
    links = []
    node_map = {} 

    for doc in reports:
        report_id = str(doc['_id'])
        nodes.append({
            "id": report_id,
            "name": (doc.get('a') or 'Untitled').split('|')[0].strip(),
            "type": "report",
            "color": "#818cf8", # Brighter Indigo
            "val": 28          # Large anchor node
        })

        raw_entities = doc.get('entities', {})
        if isinstance(raw_entities, str):
            try:
                entities = json.loads(raw_entities.strip())
            except Exception:
                entities = {"people": [], "locations": [], "organizations": []}
        else:
            entities = raw_entities
        entity_config = {
            'locations': '#10b981', # Emerald
            'people': '#3b82f6',    # Blue
            'organizations': '#f59e0b' # Amber
        }

        for cat, color in entity_config.items():
            for entity_name in entities.get(cat, []):
                ent_id = f"ent_{entity_name.lower().replace(' ', '_')}"
                
                if ent_id not in node_map:
                    node_map[ent_id] = True
                    nodes.append({
                        "id": ent_id,
                        "name": entity_name,
                        "type": cat,
                        "color": color,   
                        "val": 12          
                    })
                
                links.append({
                    "source": report_id,
                    "target": ent_id
                })

    return JsonResponse({"nodes": nodes, "links": links})


@login_required
@user_passes_test(lambda u: u.is_superuser)
def settings_view(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            action = data.get('action')

            if action == 'upsert':
                key = data['key'].strip().upper()
                obj, _ = GlobalSetting.objects.get_or_create(key=key)
                obj.value = data.get('value', '')
                obj.description = data.get('description', obj.description)
                obj.save()
                return JsonResponse({'status': 'success', 'setting': {
                    'id': obj.id, 'key': obj.key,
                    'value': obj.value, 'description': obj.description,
                    'is_known': obj.key in KNOWN_KEYS,
                }})

            elif action == 'delete':
                GlobalSetting.objects.filter(key=data['key']).delete()
                return JsonResponse({'status': 'success'})

        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

    # GET: ensure all known settings exist (seed from env var if missing)
    for s in KNOWN_SETTINGS:
        GlobalSetting.objects.get_or_create(
            key=s['key'],
            defaults={'value': os.getenv(s['env_key'], ''), 'description': s['description']},
        )

    settings_list = [
        {'id': s.id, 'key': s.key, 'value': s.value,
         'description': s.description, 'is_known': s.key in KNOWN_KEYS}
        for s in GlobalSetting.objects.all().order_by('key')
    ]
    return render(request, 'settings.html', {'settings_json': settings_list})


@login_required
@user_passes_test(lambda u: u.is_superuser)
def cron_manager_view(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            action = data.get('action')

            if action == 'create':
                job_type = data.get('job_type', 'pipeline')
                job = CronJob.objects.create(
                    name=data['name'].strip(),
                    job_type=job_type,
                    task_key=data.get('task_key', '').strip(),
                    endpoint_url=data.get('endpoint_url', '').strip(),
                    cron_expression=data['cron_expression'].strip(),
                    is_active=data.get('is_active', True),
                )
                from tasks.scheduler import load_jobs
                load_jobs()
                return JsonResponse({'status': 'success', 'job': _serialize_job(job)})

            elif action == 'update':
                job = CronJob.objects.get(id=data['id'])
                job.name = data.get('name', job.name).strip()
                job.job_type = data.get('job_type', job.job_type)
                job.task_key = data.get('task_key', job.task_key).strip()
                job.endpoint_url = data.get('endpoint_url', job.endpoint_url).strip()
                job.cron_expression = data.get('cron_expression', job.cron_expression).strip()
                job.is_active = data.get('is_active', job.is_active)
                job.save()
                from tasks.scheduler import load_jobs
                load_jobs()
                return JsonResponse({'status': 'success', 'job': _serialize_job(job)})

            elif action == 'toggle':
                job = CronJob.objects.get(id=data['id'])
                job.is_active = not job.is_active
                job.save()
                from tasks.scheduler import load_jobs
                load_jobs()
                return JsonResponse({'status': 'success', 'is_active': job.is_active})

            elif action == 'delete':
                CronJob.objects.filter(id=data['id']).delete()
                from tasks.scheduler import load_jobs
                load_jobs()
                return JsonResponse({'status': 'success'})

            elif action == 'run_now':
                job = CronJob.objects.get(id=data['id'])
                if job.job_type == 'endpoint':
                    from tasks.scheduler import run_endpoint_job
                    t = threading.Thread(
                        target=run_endpoint_job,
                        args=[job.endpoint_url, job.id],
                        daemon=True,
                    )
                    t.start()
                    return JsonResponse({'status': 'success', 'message': f"Endpoint '{job.endpoint_url}' triggered"})
                else:
                    from tasks.scheduler import run_pipeline_job
                    t = threading.Thread(
                        target=run_pipeline_job,
                        args=[job.task_key, job.id],
                        daemon=True,
                    )
                    t.start()
                    return JsonResponse({'status': 'success', 'message': f"Pipeline '{job.task_key}' triggered"})

        except CronJob.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'Job not found'}, status=404)
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

    # GET
    jobs = [_serialize_job(j) for j in CronJob.objects.all().order_by('-created_at')]
    task_keys = list(TaskConfiguration.objects.filter(is_active=True).values_list('task_key', flat=True))
    from tasks.models import DashboardFeed
    feed_keys = list(DashboardFeed.objects.filter(is_active=True).values_list('key', flat=True))
    return render(request, 'cron_manager.html', {
        'jobs_json': jobs,
        'task_keys_json': task_keys,
        'feed_keys_json': feed_keys,
    })


def _serialize_job(job):
    return {
        'id': job.id,
        'name': job.name,
        'job_type': job.job_type,
        'task_key': job.task_key,
        'endpoint_url': job.endpoint_url,
        'cron_expression': job.cron_expression,
        'is_active': job.is_active,
        'last_run_at': job.last_run_at.isoformat() if job.last_run_at else None,
        'created_at': job.created_at.isoformat() if job.created_at else None,
    }