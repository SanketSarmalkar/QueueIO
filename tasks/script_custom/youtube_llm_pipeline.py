from youtube_transcript_api import YouTubeTranscriptApi
import requests
import yt_dlp
from supadata import Supadata
from datetime import datetime, timezone
import time
import concurrent.futures
import logging
from tasks.config import get_pipeline_config, GEN_AI_CLIENT, DOCUMENT, DOCUMENT_MAP, YOUTUBE_PLAYLIST_URL_TEMPLATE, RAPID_API_KEY, RAPID_API_HOST, RAPID_API_URL, SUPADATA_API_KEY

class YouTubeLLMPipeline:
    def __init__(self, task_key="summarize"):
        cfg = get_pipeline_config()
        self.config = cfg['task_configs'].get(task_key)
        self.genai_client = GEN_AI_CLIENT
        self.model = cfg['ai_model']
        self.embedding_model = "gemini-embedding-001"
        self.collection = cfg['mongo_collections'].get(task_key)
        self.category = task_key
        self.document_template = DOCUMENT.copy()
        self.document_template.update(cfg['extra_document_args'])
        self.playlist_fetch_limit = "1-" + str(cfg['playlist_fetch_limit'])
        self.playlist_url_template = YOUTUBE_PLAYLIST_URL_TEMPLATE
        self.playlist_ids = cfg['playlist_ids']
        self.executor_workers = cfg['executor_workers']
        self.sleep_time = cfg['sleep_time']
        self.processed_video_ids = set()
        self.rapid_api_key = RAPID_API_KEY
        self.rapid_api_host = RAPID_API_HOST
        self.rapid_api_url = RAPID_API_URL
        self.supadata = Supadata(api_key=SUPADATA_API_KEY)

    def check_id_if_present(self, video_id):
        """Checks if a video ID is already processed."""
        if not video_id:
            logging.error("No video ID provided for checking.")
            return False
        
        existing = self.collection.find_one({"key": video_id})
        return existing is not None
    
    def _fetch_from_library(self, video_id):
        """Method 1: Using youtube_transcript_api (PIP)"""
        try:
            ytt_api = YouTubeTranscriptApi()
            transcript_list = ytt_api.list(video_id)
            transcript = transcript_list.find_generated_transcript(['hi', 'en'])
            return " ".join(snippet.text for snippet in transcript.fetch())
        except Exception as e:
            logging.warning(f"PIP Library failed for {video_id}: {e}")
            return None

    def _fetch_from_api(self, video_id):
        """ 
        Method 2: RapidAPI Fallback
        Parses the 'content' list from the specific JSON structure provided.
        """
        try:
            logging.info(f"Attempting RapidAPI fallback for video {video_id}...")
            url = self.rapid_api_url
            
            params = {
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "videoId": video_id,
                "lang": "en" 
            }

            headers = {
                "x-rapidapi-key": self.rapid_api_key,
                "x-rapidapi_host": self.rapid_api_host,
                "Content-Type": "application/json"
            }

            response = requests.get(url, headers=headers, params=params, timeout=20)
            
            if response.status_code == 200:
                data = response.json()
                
                content_list = data.get('content', [])
                
                if not content_list:
                    logging.warning(f"RapidAPI returned 200 but 'content' was empty for {video_id}")
                    return None
                
                full_text = " ".join(
                    snippet.get('text', '').strip() 
                    for snippet in content_list 
                    if snippet.get('text')
                )
                full_text = full_text.replace("♪", "").replace("[♪♪♪]", "").strip()
                return full_text if len(full_text) > 0 else None
            
            logging.error(f"RapidAPI Error {response.status_code}: {response.text}")
            return None

        except Exception as e:
            logging.error(f"RapidAPI request failed for {video_id}: {str(e)}")
            return None
        
    def _fetch_from_supadata(self, video_id):
        """Method 3: Supadata (Using the instance client)"""
        try:
            logging.info(f"Attempting Supadata fallback for video {video_id}...")
            response = self.supadata.youtube.transcript(video_id=video_id, text=True)
            
            if response and hasattr(response, 'content'):
                return response.content
            return None
        except Exception as e:
            logging.error(f"Supadata failed for {video_id}: {e}")
            return None

    def get_transcript(self, video):
        """Orchestrator: cache-first, then Library → RapidAPI → Supadata."""
        if not video or 'id' not in video:
            return None

        video_id = video['id']

        if self.check_id_if_present(video_id):
            logging.info(f"Skipping {video_id}: Already processed.")
            return None

        # Return cached transcript if available — avoids re-fetching on Gemini retries
        from tasks.models import TranscriptCache
        try:
            cached = TranscriptCache.objects.filter(video_id=video_id).first()
            if cached:
                logging.info(f"Transcript cache hit for {video_id}")
                return cached.transcript
        except Exception as e:
            logging.warning(f"Transcript cache lookup failed for {video_id}: {e}")

        transcript = self._fetch_from_library(video_id)
        if not transcript:
            transcript = self._fetch_from_api(video_id)
        if not transcript:
            transcript = self._fetch_from_supadata(video_id)

        if transcript:
            try:
                TranscriptCache.objects.update_or_create(
                    video_id=video_id,
                    defaults={'transcript': transcript},
                )
                logging.info(f"Transcript cached for {video_id}")
            except Exception as e:
                logging.warning(f"Failed to cache transcript for {video_id}: {e}")
            return transcript

        logging.error(f"All transcript sources failed for {video_id}")
        return None

    def run_llm_action(self, transcript):
        """Executes the configured prompt."""
        full_prompt = self.config['prompt'].format(transcript=transcript)
        try:
            response = self.genai_client.models.generate_content(
                model=self.model,
                contents=full_prompt
            )
            logging.info("LLM action executed successfully.")
            return response.text
        except Exception as e:
            logging.error(f"LLM action failed: {e}")
            return None
        
    def generate_embedding(self, text):
        """
        Generates a 3072-dimension vector.
        Optimized for Python 3.14 using the 'Simplified Batch' logic.
        """
        try:
            # We use the list format [text] to prevent NoneType response errors
            result = self.genai_client.models.embed_content(
                model=self.embedding_model,
                contents=[text]
            )
            
            # Extract values from the first item in the embeddings list
            if result and result.embeddings:
                return result.embeddings[0].values
                
            return None
        except Exception as e:
            logging.error(f"Intelligence Vectorization failed: {e}")
            return None

    def save_to_mongo(self, video, llm_result):
        """Generic insertion logic."""
        temp_doc = self.document_template.copy()
        for db_key, source_key in DOCUMENT_MAP.items():
            if source_key == "task_key":
                temp_doc['task_key'] = self.category
            elif source_key == "llm_result":
                temp_doc['value'] = llm_result
            elif source_key == "timestamp":
                v_date = video.get('date')
                temp_doc['createdat'] = v_date if v_date else datetime.now(timezone.utc)
            else:
                temp_doc[db_key] = video.get(source_key, None)

        embedding = self.generate_embedding(llm_result)
        if embedding:
            temp_doc['embedding'] = embedding
        try:
            result = self.collection.insert_one(temp_doc)
            logging.info(f"Document inserted with ID: {result.inserted_id} for video ID {video.get('id')}")
            return result.inserted_id
        except Exception as e:
            logging.error(f"Error inserting document for video ID {video.get('id')}: {e}")

    def process_video(self, video):
        """The main execution flow for one video."""
        logging.info(f"Processing: {video['id']}, {video['title']}")
        
        transcript = self.get_transcript(video)
        if not transcript: 
            return

        result = self.run_llm_action(transcript)
        if not result:
            logging.warning(f"No LLM result for video ID {video['id']}. Skipping save.")
            return

        mongo_insert = self.save_to_mongo(video, result)
        self.processed_video_ids.add(mongo_insert)
        logging.info(f"Processed and saved video ID {video['id']} with title '{video['title']}'")

    def fetch_content_metadata(self, url, playlist_id=None, custom_opts=None):
        """
        A generic wrapper for yt-dlp that extracts entries 
        based on a passed configuration.
        """
        # Default generic options
        base_opts = {
            'extract_flat': True,
            'quiet': True,
            'playlist_items': self.playlist_fetch_limit, 
        }
        if custom_opts:
            base_opts.update(custom_opts)

        found_items = []
        with yt_dlp.YoutubeDL(base_opts) as ydl:
            try:
                result = ydl.extract_info(url, download=False)
                entries = result.get('entries', [result]) 
                playlist_name = result.get('title', 'General Archive')
                for entry in entries:
                    if not entry: continue

                    found_items.append({
                        'id': entry.get('id'),
                        'title': entry.get('title'),
                        'date': entry.get('upload_date'),
                        'playlist_id': playlist_id,
                        'playlist_title': playlist_name,
                        'url': entry.get('url') or f"https://www.youtube.com/watch?v={entry.get('id')}"
                    })
            except Exception as e:
                logging.error(f"Error fetching from {url}: {e}")
        return found_items
    
    def fetch_videos_from_playlists(self):
        """Fetches videos from configured playlists using the generic metadata fetcher."""
        all_videos = []
        for playlist_id in self.playlist_ids:
            if not playlist_id.strip():
                continue
            playlist_url = self.playlist_url_template.format(playlist_id=playlist_id)
            videos = self.fetch_content_metadata(playlist_url, playlist_id=playlist_id)
            all_videos.extend(videos)
        return all_videos
    
    def run_pipeline(self):
        """The main execution flow for the entire pipeline."""
        videos = self.fetch_videos_from_playlists()
        logging.info(f"Total videos fetched: {len(videos)}")
        videos.reverse()  # Process older videos first
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.executor_workers) as executor:
            executor.map(self.process_video, videos)
            time.sleep(self.sleep_time)

        if self.processed_video_ids:
            logging.info(f"Pipeline completed. Processed video IDs: {self.processed_video_ids}")
            return list(self.processed_video_ids)
        else:
            logging.info("Pipeline completed. No videos were processed.")
            return []