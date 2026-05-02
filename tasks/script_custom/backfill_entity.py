import os
import sys
import time
import json
import django
from pymongo import MongoClient
from google import genai

sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

def backfill_entities():
    client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
    
    db_password = os.getenv('DB_PASSWORD').replace('"', '')
    db_user = os.getenv('DB_USER').replace('"', '')
    db_url = os.getenv('DB_URL').replace('"', '')
    uri = f"mongodb+srv://{db_user}:{db_password}@{db_url}/?appName=Cluster0"
    mongo_client = MongoClient(uri)
    collection = mongo_client["queuei"]["mass_records"]

    reports = list(collection.find({"entities": {"$exists": False}}))
    print(f"🚀 Found {len(reports)} reports needing analysis.")

    for doc in reports:
        print(f"🔍 Analyzing: {doc.get('a', 'Untitled')[:50]}...")
        
        prompt = f"""
        Extract key intelligence entities from this report. 
        Return ONLY a JSON object with keys: "people", "locations", "organizations".
        
        REPORT:
        {doc.get('value')}
        """
        
        success = False
        retries = 0
        while not success and retries < 3:
            try:
                response = client.models.generate_content(
                    model="gemini-3.1-flash-lite-preview",
                    contents=prompt,
                    config={"response_mime_type": "application/json"}
                )
                
                # Parse and Save
                entity_data = json.loads(response.text)
                collection.update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"entities": entity_data}}
                )
                print(f"✅ Extracted entities for {doc['_id']}")
                
                success = True
                time.sleep(5) 

            except Exception as e:
                if "429" in str(e):
                    print("🛑 Quota hit. Sleeping for 45 seconds...")
                    time.sleep(45)
                    retries += 1
                else:
                    print(f"❌ Critical Error on {doc['_id']}: {e}")
                    break

if __name__ == "__main__":
    backfill_entities()