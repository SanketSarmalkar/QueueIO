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
from bson import ObjectId

import threading
from tasks.models import TaskConfiguration, GlobalSetting, CronJob
from django.contrib.auth.decorators import user_passes_test

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
    stack_pipeline = [
        {"$group": {"_id": "$playlist_id", "count": {"$sum": 1}, "title": {"$first": "$playlist_title"}}},
        {"$sort": {"count": -1}},
    ]
    stacks_json = [
        {"id": s["_id"] or "unassigned", "count": s["count"], "title": s.get("title") or "General Archive"}
        for s in collection.aggregate(stack_pipeline)
    ]

    total = collection.estimated_document_count()
    records = list(collection.find({}, {'value': 0, 'embedding': 0}).sort('createdat', -1).limit(_PAGE_SIZE))
    formatted_items = [_format_record(r) for r in records]

    tasks_list = list(TaskConfiguration.objects.all().values(
        'id', 'task_key', 'display_name', 'prompt_template', 'target_collection', 'is_active'
    ))

    return render(request, 'dashboard.html', {
        'items_raw': formatted_items,
        'latest_id': formatted_items[0]['id'] if formatted_items else '',
        'tasks_json': tasks_list,
        'stacks_json': stacks_json,
        'total_count': total,
        'has_more': 'true' if total > _PAGE_SIZE else 'false',
        'next_offset': _PAGE_SIZE,
    })


@login_required
def get_more_records(request):
    offset = int(request.GET.get('offset', _PAGE_SIZE))
    collection = get_db_collection()
    total = collection.estimated_document_count()
    records = list(collection.find({}, {'value': 0, 'embedding': 0}).sort('createdat', -1).skip(offset).limit(_PAGE_SIZE))
    return JsonResponse({
        'items': [_format_record(r) for r in records],
        'has_more': offset + _PAGE_SIZE < total,
        'next_offset': offset + _PAGE_SIZE,
    })

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
        "playlist_id": report.get('playlist_id'),
        "playlist_title": report.get('playlist_title', ''),
    })

_PAGE_SIZE = 50

def get_db_collection():
    from tasks.config import MONGO_DB
    return MONGO_DB["mass_records"]

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
        'playlist_id': item.get('playlist_id', None),
        'playlist_title': item.get('playlist_title', item.get('playlist_id', 'General Archive')),
    }

@login_required
def intel_chat_view(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            user_query = data.get('query')

            client = genai.Client(api_key=os.getenv("GEN_AI_API_KEY"))
            collection = get_db_collection()

            query_res = client.models.embed_content(
                model="gemini-embedding-001",
                contents=[user_query]
            )
            query_vector = query_res.embeddings[0].values

            pipeline = [
                {
                    "$vectorSearch": {
                        "index": "vector_index",
                        "path": "embedding",
                        "queryVector": query_vector,
                        "numCandidates": 100,
                        "limit": 5
                    }
                },
                {
                    "$project": {
                        "a": 1, 
                        "value": 1, 
                        "playlist_title": 1,
                        "score": {"$meta": "vectorSearchScore"}
                    }
                }
            ]
            context_reports = list(collection.aggregate(pipeline))

            context_text = "\n\n".join([
                f"REPORT: {r['a']}\nSUMMARY: {r['value']}"
                for r in context_reports
            ])

            prompt = f"""
            You are a Senior Intelligence Analyst. Provide a concise, professional synthesis 
            to the following query based ONLY on the archive data provided below.
            
            QUERY: {user_query}
            
            ARCHIVE DATA:
            {context_text}
            """
            
            llm_res = client.models.generate_content(
                model="gemini-3.1-flash-lite-preview", 
                contents=prompt
            )

            return JsonResponse({
                "answer": llm_res.text,
                "sources": [{"title": str(r['a']).split('|')[0].strip()} for r in context_reports]
            })
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
            "name": doc.get('a', 'Untitled').split('|')[0].strip(),
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
    return render(request, 'cron_manager.html', {
        'jobs_json': jobs,
        'task_keys_json': task_keys,
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