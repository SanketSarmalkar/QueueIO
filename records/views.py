from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout
from pymongo import MongoClient
from django.conf import settings
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login
from django.contrib import messages
from django.http import JsonResponse
from datetime import datetime
from google import genai
import os
import json
from bson import ObjectId
from pymongo.server_api import ServerApi

from tasks.models import TaskConfiguration, GlobalSetting
from django.contrib.auth.decorators import user_passes_test


def custom_404(request, exception):
    return render(request, '404.html', status=404)

@login_required
def dashboard(request):
    is_authorized = request.user.groups.filter(name__in=['Analyst', 'Supervisor']).exists()
    if not is_authorized:
        return render(request, 'access_denied.html')

    collection = get_db_collection()
    
    records = list(collection.find({}, {'value': 0, 'embedding': 0}).sort('createdat', -1))
    
    formatted_items = []
    for item in records:
        created_at = item.get('createdat')
        date_display = "N/A"
        time_display = "N/A"
        if created_at:
            if isinstance(created_at, str):
                created_at = datetime.fromisoformat(created_at)
            if hasattr(created_at, "strftime"):
                date_display = created_at.strftime("%b %d, %Y")
            if hasattr(created_at, "strftime"):
                time_display = created_at.strftime('%I:%M %p')
        formatted_items.append({
            'id': str(item['_id']),
            'category': item.get('category', 'queuei'),
            'key': item.get('key', ''),
            'title': item.get('a', 'Untitled Record').split('|')[0].strip(),
            # 'value': item.get('value', ''),
            'date_display': date_display,
            'time_display': time_display,
            'playlist_id': item.get('playlist_id', None),
            'playlist_title': item.get('playlist_title', item.get('playlist_id', 'General Archive'))
        })

    tasks_query = TaskConfiguration.objects.all().values(
        'id', 'task_key', 'display_name', 'prompt_template', 'target_collection', 'is_active'
    )
    tasks_list = list(tasks_query)
        
    return render(request, 'dashboard.html', {
        'items_raw': formatted_items,
        'latest_id': formatted_items[0]['id'] if formatted_items else '',
        'tasks_json': tasks_list
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
    report = collection.find_one({"_id": ObjectId(report_id)}, {"value": 1, "entities": 1})
    raw_entities = report.get('entities', '{}')
    if isinstance(raw_entities, str):
        try:
            entities_data = json.loads(raw_entities.strip())
        except Exception:
            entities_data = {"people": [], "locations": [], "organizations": []}
    else:
        entities_data = raw_entities

    return JsonResponse({
        "value": report.get('value', 'No content found.'),
        "entities": entities_data
    })

def get_db_collection():
    db_password = os.getenv('DB_PASSWORD', '').replace('"', '')
    db_user = os.getenv('DB_USER', '').replace('"', '')
    db_url = os.getenv('DB_URL', '').replace('"', '')
    uri = f"mongodb+srv://{db_user}:{db_password}@{db_url}/?appName=Cluster0"
    client = MongoClient(uri, server_api=ServerApi('1'))
    return client["queuei"]["mass_records"]

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
    reports = list(collection.find({"entities": {"$exists": True}}).sort('createdat', -1).limit(500))
    
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