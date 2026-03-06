import os
from dotenv import load_dotenv

from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi

import json

from google import genai

load_dotenv()

TASK_CONFIGS = {
    "raw":{
        "prompt": None,
        "collection": "raw_transcripts",
    },
    "summarize": {
        "prompt": "Summarize the following transcript in a concise manner and in depth in English and in markdown format: {transcript}",
        "collection": "mass_records",
    },
    "extract_action_items": {
        "prompt": "Extract a bulleted list of action items from this transcript: {transcript}",
        "collection": "action_items",
    },
    "sentiment_analysis": {
        "prompt": "Analyze the sentiment of this video: {transcript}",
        "collection": "analytics",
    }
}

MONGO_URL = "mongodb+srv://{db_user}:{db_password}@{db_url}/?appName=Cluster0".format(
    db_user=os.getenv('DB_USER').replace('"', ''),
    db_password=os.getenv('DB_PASSWORD').replace('"', ''),
    db_url=os.getenv('DB_URL').replace('"', '')
)
MONGO_CLIENT = MongoClient(MONGO_URL, server_api=ServerApi('1'))
MONGO_DB = MONGO_CLIENT[os.getenv('MONGO_DB_NAME', 'queuei')]
MONGO_COLLECTIONS = {key: MONGO_DB[config['collection']] for key, config in TASK_CONFIGS.items()}
EXTRA_DOCUMENT_ARGS = json.loads(os.getenv('EXTRA_DOCUMENT_ARGS', '{}').replace("'", '"'))
DOCUMENT = {
    "category": None, # This will be set to the task key (e.g., "summarize", "extract_action_items", etc.)
    "key": None, # This will be set to the video ID or a unique identifier for the video
    "a": None, # This can be used for any additional metadata you want to store (e.g., video title, date, etc.)
    "value": None, # This will be set to the result of the LLM action (e.g., summary text, list of action items, sentiment analysis result, etc.)
    "createdat": None # This will be set to the current timestamp when the document is created
    # You can add more fields here as needed, and they will be populated from EXTRA_DOCUMENT_ARGS if provided
}
DOCUMENT_MAP = {
    "category": "task_key",       # Use the task name
    "key": "id",                 # Use video['id']
    "a": "title",                # Use video['title']
    "value": "llm_result",       # Special flag for AI output
    "createdat": "timestamp"     # Special flag for current time
}

AI_MODEL = os.getenv('AI_MODEL', 'gemini-3-flash-preview')
GEN_AI_CLIENT = genai.Client(api_key=os.getenv('GOOGLE_API_KEY'))

PLAYLIST_FETCH_LIMIT = int(os.getenv('PLAYLIST_FETCH_LIMIT', '10'))
YOUTUBE_PLAYLIST_URL_TEMPLATE = 'https://www.youtube.com/playlist?list={playlist_id}'
YOUTUBE_PLAYLIST_IDS = os.getenv('YOUTUBE_PLAYLIST_IDS', '').split(',')

EXECUTOR_WORKERS = int(os.getenv('EXECUTOR_WORKERS', '1'))
INBETWEEN_TASK_SLEEP = int(os.getenv('INBETWEEN_TASK_SLEEP', '15'))

SLACK_WEBHOOK_URL = os.getenv('SLACK_WEBHOOK_URL', '')