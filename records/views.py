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
from pymongo.server_api import ServerApi

def custom_404(request, exception):
    return render(request, '404.html', status=404)

@login_required
def dashboard(request):
    is_authorized = request.user.groups.filter(name__in=['Analyst', 'Supervisor']).exists()
    if not is_authorized:
        return render(request, 'access_denied.html')

    collection = get_db_collection()
    
    records = list(collection.find().sort('createdat', -1))
    
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
            'value': item.get('value', ''),
            'date_display': date_display,
            'time_display': time_display,
            'playlist_id': item.get('playlist_id', None),
            'playlist_title': item.get('playlist_title', item.get('playlist_id', 'General Archive'))
        })
        
    return render(request, 'dashboard.html', {
        'items_raw': formatted_items,
        'latest_id': formatted_items[0]['id'] if formatted_items else ''
    })

def logout_view(request):
    logout(request)
    return redirect('login')

# def signup_view(request):
#     if request.method == 'POST':
#         form = UserCreationForm(request.POST)
#         if form.is_valid():
#             user = form.save()
#             login(request, user) # Log the user in immediately after signup
#             return redirect('dashboard')
#     else:
#         form = UserCreationForm()
#     return render(request, 'signup.html', {'form': form})

def signup_view(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            # BLOCK ACCESS: New users are not active until Admin says so
            user.is_active = False 
            user.save()
            
            # Show a terminal-style success message
            messages.success(request, "ACCESS REQUEST SENT. AWAITING SUPERVISOR AUTHORIZATION.")
            return redirect('login')
    else:
        form = UserCreationForm()
    return render(request, 'signup.html', {'form': form})

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