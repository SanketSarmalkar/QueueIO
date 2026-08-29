import os
import yt_dlp
from pymongo import MongoClient
from pymongo.server_api import ServerApi
from datetime import datetime, timezone
from dotenv import load_dotenv
from django.http import JsonResponse

load_dotenv()

def backfill_playlist_data(request = None):
    try:
        db_password = os.getenv('DB_PASSWORD', '').replace('"', '')
        db_user = os.getenv('DB_USER', '').replace('"', '')
        db_url = os.getenv('DB_URL', '').replace('"', '')
        uri = f"mongodb+srv://{db_user}:{db_password}@{db_url}/?appName=Cluster0"
        
        print(f"Connecting to Cluster: {db_url}...")
        client = MongoClient(uri, server_api=ServerApi('1'), serverSelectionTimeoutMS=5000)
        
        db = client["queuei"]
        collection = db["mass_records"]
        client.admin.command('ping')
        print("✅ MongoDB Connected Successfully.")
    except Exception as e:
        print(f"❌ Connection Failed: {e}")
        return JsonResponse({
            "status": "error",
            "message": "Failed to connect to MongoDB. Check console for details."
        })

    from tasks.config import get_global_setting
    playlist_ids_raw = get_global_setting('YOUTUBE_PLAYLIST_IDS', os.getenv('YOUTUBE_PLAYLIST_IDS', ''))
    playlist_ids = [p.strip() for p in playlist_ids_raw.split(',') if p.strip()]
    ydl_opts = {'extract_flat': True, 'quiet': True}

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        for p_id in playlist_ids:
            p_id = p_id.strip()
            if not p_id: continue
            
            print(f"📂 Syncing Playlist: {p_id}")
            try:
                result = ydl.extract_info(f"https://www.youtube.com/playlist?list={p_id}", download=False)
                playlist_title = result.get('title', 'General Archive')
                video_ids = [e.get('id') for e in result.get('entries', []) if e]

                if not video_ids:
                    print(f"   ⚠️ No videos found in {p_id}")
                    continue
                query = {
                    "key": {"$in": video_ids},
                    "$or": [
                        {"playlist_id": {"$exists": False}},
                        {"playlist_id": None},
                        {"playlist_id": "unassigned"}
                    ]
                }
                
                update_data = {
                    "$set": {
                        "playlist_id": p_id,
                        "playlist_title": playlist_title
                    }
                }

                res = collection.update_many(query, update_data)
                print(f"   ✨ Successfully updated {res.modified_count} records -> [{playlist_title}]")

            except Exception as e:
                print(f"   ⚠️ Could not fetch YouTube data for {p_id}: {e}")
                return JsonResponse({
                    "status": "error",
                    "message": f"Failed to fetch YouTube data for {p_id}. Check console for details."
                })

    print("\n🚀 Migration Complete. Restart your Django server to see the stacks!")
    return JsonResponse({
        "status": "success",
        "message": "Backfill complete. Check console for details."
    })

def get_db_collection():
    """Helper to maintain connection logic in one place."""
    db_password = os.getenv('DB_PASSWORD', '').replace('"', '')
    db_user = os.getenv('DB_USER', '').replace('"', '')
    db_url = os.getenv('DB_URL', '').replace('"', '')
    uri = f"mongodb+srv://{db_user}:{db_password}@{db_url}/?appName=Cluster0"
    
    client = MongoClient(uri, server_api=ServerApi('1'), serverSelectionTimeoutMS=5000)
    db = client["queuei"]
    return db["mass_records"]

def force_fix_titles():
    try:
        collection = get_db_collection()
        print("✅ MongoDB Connected Successfully.")
        
        # 1. Setup the target
        target_id = "PLgeZhmWMhjb9gObDI-BKYIBetS-U5pD1X"
        print(f"🔍 Fetching latest metadata from YouTube for: {target_id}")
        
        # 2. Fetch the video IDs again so we have 'video_ids_from_yt'
        ydl_opts = {'extract_flat': True, 'quiet': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(f"https://www.youtube.com/playlist?list={target_id}", download=False)
            target_title = result.get('title', "World News || ANI News 2026")
            video_ids_from_yt = [e.get('id') for e in result.get('entries', []) if e]

        if not video_ids_from_yt:
            print("❌ No videos found in playlist. Check the ID.")
            return

        print(f"🚀 Force updating {len(video_ids_from_yt)} potential records for: {target_title}")
        
        # 3. Perform the update
        # We REMOVE the '$or' check so we overwrite those 3 stubborn records
        res = collection.update_many(
            {"key": {"$in": video_ids_from_yt}},
            {"$set": {
                "playlist_id": target_id, 
                "playlist_title": target_title
            }}
        )
        
        print(f"✨ SUCCESS: {res.modified_count} records were actually corrected.")
        print("Check your dashboard now.")

    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    backfill_playlist_data()
    # force_fix_titles()