import os
from dotenv import load_dotenv

from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
import django
import json
from django.db import connection

from google import genai

load_dotenv()

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from tasks.models import TaskConfiguration, GlobalSetting

# TASK_CONFIGS = {
#     "raw":{
#         "prompt": None,
#         "collection": "raw_transcripts",
#     },
#     "summarize": {
#         "prompt": "Summarize the following transcript in a concise manner and in depth in English and in markdown format: {transcript}",
#         "collection": "mass_records",
#     },
#     "extract_action_items": {
#         "prompt": "Extract a bulleted list of action items from this transcript: {transcript}",
#         "collection": "action_items",
#     },
#     "sentiment_analysis": {
#         "prompt": "Analyze the sentiment of this video: {transcript}",
#         "collection": "analytics",
#     }
# }

def get_dynamic_configs():
    # --- FALLBACK DEFAULTS ---
    # These will be used if the DB isn't migrated yet
    default_tasks = {
        "summarize": {
            "prompt": "Summarize the following transcript in a concise manner and in depth in English and in markdown format: {transcript}",
            "collection": "mass_records",
        }
    }
    default_limit = 10
    default_model = 'gemini-2.0-flash'

    # Check if the tables exist before querying
    # This prevents the "UndefinedTable" error during migrations
    table_name = TaskConfiguration._meta.db_table
    if table_name not in connection.introspection.table_names():
        return default_tasks, default_limit, default_model

    try:
        # 1. Fetch Task Configs
        db_tasks = TaskConfiguration.objects.filter(is_active=True)
        task_configs = {}
        if db_tasks.exists():
            for t in db_tasks:
                task_configs[t.task_key] = {
                    "prompt": t.prompt_template,
                    "collection": t.target_collection
                }
        else:
            task_configs = default_tasks

        # 2. Fetch Global Settings
        try:
            fetch_limit = int(GlobalSetting.objects.get(key='PLAYLIST_FETCH_LIMIT').value)
        except GlobalSetting.DoesNotExist:
            fetch_limit = default_limit

        try:
            ai_model = GlobalSetting.objects.get(key='AI_MODEL').value
        except GlobalSetting.DoesNotExist:
            ai_model = default_model

        return task_configs, fetch_limit, ai_model

    except Exception as e:
        # If anything goes wrong (DB connection, etc.), use defaults
        print(f"⚠️  Database not ready, using defaults. Error: {e}")
        return default_tasks, default_limit, default_model

TASK_CONFIGS, PLAYLIST_FETCH_LIMIT, AI_MODEL = get_dynamic_configs()


def get_global_setting(key, default=''):
    """Read a single GlobalSetting from DB; fall back to default if missing."""
    table_name = GlobalSetting._meta.db_table
    if table_name not in connection.introspection.table_names():
        return default
    try:
        return GlobalSetting.objects.get(key=key).value
    except GlobalSetting.DoesNotExist:
        return default
    except Exception:
        return default


def get_pipeline_config():
    """
    Returns a fresh copy of all pipeline settings from the DB on every call.
    Use this inside YouTubeLLMPipeline.__init__ so changes take effect without restarts.
    """
    task_configs, _, _ = get_dynamic_configs()

    playlist_ids_raw = get_global_setting('YOUTUBE_PLAYLIST_IDS', os.getenv('YOUTUBE_PLAYLIST_IDS', ''))
    playlist_ids = [p.strip() for p in playlist_ids_raw.split(',') if p.strip()]

    fetch_limit = int(get_global_setting('PLAYLIST_FETCH_LIMIT', os.getenv('PLAYLIST_FETCH_LIMIT', '10')))
    ai_model = get_global_setting('AI_MODEL', os.getenv('AI_MODEL', 'gemini-2.0-flash'))
    executor_workers = int(get_global_setting('EXECUTOR_WORKERS', os.getenv('EXECUTOR_WORKERS', '1')))
    sleep_time = int(get_global_setting('INBETWEEN_TASK_SLEEP', os.getenv('INBETWEEN_TASK_SLEEP', '15')))

    extra_args_raw = get_global_setting('EXTRA_DOCUMENT_ARGS', os.getenv('EXTRA_DOCUMENT_ARGS', '{}'))
    try:
        extra_document_args = json.loads(extra_args_raw.replace("'", '"'))
    except Exception:
        extra_document_args = {}

    mongo_collections = {key: MONGO_DB[cfg['collection']] for key, cfg in task_configs.items()}

    return {
        'task_configs': task_configs,
        'ai_model': ai_model,
        'playlist_ids': playlist_ids,
        'playlist_fetch_limit': fetch_limit,
        'executor_workers': executor_workers,
        'sleep_time': sleep_time,
        'extra_document_args': extra_document_args,
        'mongo_collections': mongo_collections,
    }

MONGO_URL = "mongodb+srv://{db_user}:{db_password}@{db_url}/?appName=Cluster0".format(
    db_user=os.getenv('DB_USER').replace('"', ''),
    db_password=os.getenv('DB_PASSWORD').replace('"', ''),
    db_url=os.getenv('DB_URL').replace('"', '')
)

_mongo_client = None
_mongo_db = None

def _get_mongo_db():
    global _mongo_client, _mongo_db
    if _mongo_db is None:
        _mongo_client = MongoClient(MONGO_URL, server_api=ServerApi('1'))
        _mongo_db = _mongo_client[os.getenv('MONGO_DB_NAME', 'queuei')]
    return _mongo_db

class _LazyMongoDB:
    def __getitem__(self, key):
        return _get_mongo_db()[key]
    def __getattr__(self, key):
        return getattr(_get_mongo_db(), key)

MONGO_DB = _LazyMongoDB()
MONGO_CLIENT = None  # use _get_mongo_db() directly if needed
MONGO_COLLECTIONS = {key: MONGO_DB[config['collection']] for key, config in TASK_CONFIGS.items()}
EXTRA_DOCUMENT_ARGS = json.loads(os.getenv('EXTRA_DOCUMENT_ARGS', '{}').replace("'", '"'))
DOCUMENT = {
    "category": None,
    "key": None,
    "a": None,
    "value": None,
    "createdat": None,
    "playlist_id": None,
    "playlist_title": None,
}
DOCUMENT_MAP = {
    "category": "task_key",
    "key": "id",
    "a": "title",
    "value": "llm_result",
    "createdat": "timestamp",
    "playlist_id": "playlist_id",
    "playlist_title": "playlist_title",
}

AI_MODEL = os.getenv('AI_MODEL', 'gemini-3-flash-preview')
GEN_AI_CLIENT = genai.Client(api_key=os.getenv('GOOGLE_API_KEY'))

PLAYLIST_FETCH_LIMIT = int(os.getenv('PLAYLIST_FETCH_LIMIT', '10'))
YOUTUBE_PLAYLIST_URL_TEMPLATE = 'https://www.youtube.com/playlist?list={playlist_id}'
YOUTUBE_PLAYLIST_IDS = os.getenv('YOUTUBE_PLAYLIST_IDS', '').split(',')

EXECUTOR_WORKERS = int(os.getenv('EXECUTOR_WORKERS', '1'))
INBETWEEN_TASK_SLEEP = int(os.getenv('INBETWEEN_TASK_SLEEP', '15'))

SLACK_WEBHOOK_URL = os.getenv('SLACK_WEBHOOK_URL', '')

RAPID_API_KEY = os.getenv('RAPID_API_KEY', '')
RAPID_API_HOST = os.getenv('RAPID_API_HOST', '')
RAPID_API_URL = os.getenv('RAPID_API_URL', '')

SUPADATA_API_KEY = os.getenv('SUPADATA_API_KEY', '')