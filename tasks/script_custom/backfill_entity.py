import os
import sys
import time
import json
import django

sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from google import genai
from tasks.config import MONGO_DB, get_global_setting


@csrf_exempt
def backfill_entities(request=None):
    ai_model = get_global_setting('AI_MODEL', os.getenv('AI_MODEL', 'gemini-2.0-flash'))
    client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
    collection = MONGO_DB["mass_records"]

    reports = list(collection.find({"entities": {"$exists": False}}, {"_id": 1, "a": 1, "value": 1}))
    total = len(reports)
    print(f"Found {total} reports needing entity extraction.")

    processed = 0
    failed = 0

    for doc in reports:
        title = (doc.get('a') or 'Untitled')[:50]
        value = doc.get('value') or ''
        if not value:
            print(f"  Skipping {doc['_id']} — no value field")
            failed += 1
            continue

        print(f"  Analyzing: {title}...")

        prompt = f"""Extract key intelligence entities from this report.
Return ONLY a JSON object with keys: "people", "locations", "organizations".
Each key maps to an array of strings.

REPORT:
{value}"""

        success = False
        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model=ai_model,
                    contents=prompt,
                    config={"response_mime_type": "application/json"}
                )
                entity_data = json.loads(response.text)
                collection.update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"entities": entity_data}}
                )
                print(f"  Done: {doc['_id']}")
                processed += 1
                success = True
                time.sleep(4)
                break

            except Exception as e:
                if "429" in str(e):
                    wait = 60 * (attempt + 1)
                    print(f"  Rate limited. Sleeping {wait}s...")
                    time.sleep(wait)
                else:
                    print(f"  Error on {doc['_id']}: {e}")
                    break

        if not success:
            failed += 1

    print(f"Backfill complete. Processed: {processed}, Failed: {failed}, Total: {total}")
    return JsonResponse({
        "status": "success",
        "processed": processed,
        "failed": failed,
        "total": total,
    })


if __name__ == "__main__":
    backfill_entities()
