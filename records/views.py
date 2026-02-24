from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout
from pymongo import MongoClient
from django.conf import settings
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login
from django.contrib import messages
from datetime import datetime
import json

@login_required
def dashboard(request):
    is_authorized = request.user.groups.filter(name__in=['Analyst', 'Supervisor']).exists()
    if not is_authorized:
        return render(request, 'access_denied.html')

    uri = getattr(settings, "MONGO_URI", "mongodb://localhost:27017/")
    db_name = getattr(settings, "MONGO_DB_NAME", "queuei")
    
    client = MongoClient(uri)
    db = client[db_name]
    collection = db['mass_records']
    
    records = list(collection.find().sort('createdat', -1))
    
    formatted_items = []
    for item in records:
        created_at = item.get('createdat')
        date_display = "N/A"
        if created_at:
            if isinstance(created_at, str):
                created_at = datetime.fromisoformat(created_at)
            if hasattr(created_at, "strftime"):
                date_display = created_at.strftime("%b %d, %Y")
        formatted_items.append({
            'id': str(item['_id']),
            'category': item.get('category', 'queuei'),
            'key': item.get('key', ''),
            'title': item.get('a', 'Untitled Record').split('|')[0].strip(),
            'value': item.get('value', ''),
            'date_display': date_display
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