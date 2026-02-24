from django.shortcuts import render
from youtube_transcript_api import YouTubeTranscriptApi
from dotenv import load_dotenv
from google import genai
import yt_dlp
from datetime import datetime, timedelta, timezone
import time
import urllib.parse
import concurrent.futures
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
import os

load_dotenv() 

URL = 'https://www.youtube.com/playlist?list=PL2TgM-3jib3nGWxh1ZkMPHwsWBe4XAErF'
CUSTOM_DATE = ['{date:%Y-%m-%d}'.format(date=datetime.now() - timedelta(days=1)), '{date:%Y-%m-%d}'.format(date=datetime.now())]
db_password = os.getenv('DB_PASSWORD').replace('"', '')
db_user = os.getenv('DB_USER').replace('"', '')
db_url = os.getenv('DB_URL').replace('"', '')
genai_key = os.getenv('GOOGLE_API_KEY').replace('"', '')
uri = f"mongodb+srv://{db_user}:{db_password}@{db_url}/?appName=Cluster0"
client = MongoClient(uri, server_api=ServerApi('1'))


class Silencer:
    def debug(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass

def fetch_video_metadata(url, ydl_instance, search_set):
    """Fetches minimal metadata for a single video and checks the date."""
    try:
        info = ydl_instance.extract_info(url, download=False, process=False)
        
        if not info:
            return None
            
        v_date = info.get('upload_date')
        
        if v_date in search_set:
            return {
                'title': info.get('title'),
                'id': info.get('id'),
                'date': v_date,
                'url': url
            }
    except Exception:
        pass 
        
    return None

def get_videos_by_dates(playlist_url, target_dates_list):
    search_set = set()
    
    for d in target_dates_list:
        try:
            formatted_date = datetime.strptime(d, '%Y-%m-%d').strftime('%Y%m%d')
            search_set.add(formatted_date)
        except ValueError:
            print(f"Skipping invalid date format: {d}. Use YYYY-MM-DD.")

    if not search_set:
        print("No valid dates to search for.")
        return []

    print(f"Searching for videos from these dates: {', '.join(target_dates_list)}...")
    playlist_opts = {
        'extract_flat': 'in_playlist',
        'quiet': True,
        'no_warnings': True,
        'logger': Silencer(),
        'ignoreerrors': True,
    }

    video_urls = []
    with yt_dlp.YoutubeDL(playlist_opts) as ydl:
        playlist_info = ydl.extract_info(playlist_url, download=False)
        
        if playlist_info and 'entries' in playlist_info:
            for entry in playlist_info['entries']:
                if entry and entry.get('url'):
                    video_urls.append(entry.get('url'))

    if not video_urls:
        print("No videos found in the playlist.")
        return []

    print(f"Playlist map fetched. Checkingq {len(video_urls)} videos concurrently...")
    target_urls = video_urls[0:10]

    video_opts = {
        'extract_flat': False,
        'quiet': True,
        'no_warnings': True,
        'logger': Silencer(),
        'ignoreerrors': True,
    }

    found_videos = []
    
    with yt_dlp.YoutubeDL(video_opts) as ydl:
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(fetch_video_metadata, url, ydl, search_set) for url in target_urls]
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                if result:
                    found_videos.append(result)

    found_videos.sort(key=lambda x: x['date'])

    if found_videos:
        print(f"\n✅ Total Matches Found: {len(found_videos)}")
        for vid in found_videos:
            print(f"[{vid['date']}] - {vid['title']} (ID: {vid['id']})")
    else:
        print("No videos matched any of the provided dates.")
            
    return found_videos

def generate_text(prompt):
    client = genai.Client(api_key=genai_key)

    response = client.models.generate_content(
        model="gemini-3-flash-preview",
        contents=prompt
    )
    return response.text

def insert_record(sno, category="None", key="None", name="None", value="None", createdat=None):
    """Inserts a record with an automated timestamp"""
    db = client["queuei"] 
    collection = db["mass_records"]
    document = {
        "sno": sno,
        "category": category,
        "key": key,
        "a": name.split('|')[0].strip(),
        "value": value,
        "createdat": createdat if createdat else datetime.now(timezone.utc)
    }
    
    try:
        result = collection.insert_one(document)
        print(f"Successfully inserted document with ID: {result.inserted_id}")
    except Exception as e:
        print(f"Error inserting document: {e}")


def check_id_if_present(video_id):
    """
    Checks if a document exists with the 'key' field matching video_id.
    Returns True if found, False otherwise.
    """
    db = client["queuei"]
    collection = db["mass_records"]
    result = collection.find_one({"key": video_id}, {"_id": 1})
    return result is not None

def main(video):
    if not video or 'id' not in video:
        print("Invalid video data provided.")
        return
    video_id = video['id']
    video_creation_date = video.get('date', None)
    video_title = video.get('title', 'Unknown Title')
    if video_id is None:
        print("No video ID provided.")
        return
    
    if check_id_if_present(video_id):
        print(f"Video ID {video_id} already processed. Skipping.")
        return
    
    else:
        print(f"Processing video ID: {video_id}")

    try:
        ytt_api = YouTubeTranscriptApi()
        # fetched_transcript = ytt_api.fetch(video_id)
        transcript_list = ytt_api.list(video_id)
        # for snippet in fetched_transcript:
        #     print(snippet.text)
        # print(transcript_list)
        transcript = transcript_list.find_generated_transcript(['hi'])
        # final_transcript = transcript.translate('en')
        final_transcript = ''
        for snippet in transcript.fetch():
            final_transcript+= snippet.text + ' '
        # return final_transcript
        gen_response = generate_text(final_transcript+ "\n\nSummarize the above text in a concise manner in detail..")
        try:
            insert_record(sno=1, category="queuei", key=video_id, name=video_title, value=gen_response, createdat=video_creation_date)
        except Exception as e:
            print(f"Error inserting transcript into database: {e}")
    except Exception as e:
        print(f"Error: {e}")
        return None 

# if __name__ == "__main__":
@csrf_exempt
def run_task(request):
    if request.method == 'POST':
        start_time = time.perf_counter()
        print(f"Checking for videos on dates: {CUSTOM_DATE} in playlist: {URL}")
        vid_id = get_videos_by_dates(URL, CUSTOM_DATE)
        if len(vid_id) > 0:
            for vid in vid_id:
                print(f"Generating summary for video ID: {vid['id']}")
                main(vid)
                # break
                time.sleep(30)
                print("--------------------------------------------------------------")
        end_time = time.perf_counter()
        total_duration = end_time - start_time
        print(f"\n⏱️  Execution completed in: {total_duration:.2f} seconds")
        return JsonResponse({
                    'status': 'success',
                    'message': f'Task executed successfully',
                    'timestamp': datetime.now().isoformat()
                })

