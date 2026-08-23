from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
import logging
import json
import os
from django.shortcuts import render
from .script_custom.youtube_llm_pipeline import YouTubeLLMPipeline
from .script_custom.slack_alerting import send_slack_alert

_TASK_SECRET = os.getenv('TASK_SECRET', '')


def _authorized(request):
    """Return True if the request carries a valid task secret (or none is configured)."""
    if not _TASK_SECRET:
        return True
    return request.headers.get('X-Task-Secret', '') == _TASK_SECRET


@csrf_exempt
def run_task(request, task_key):
    if request.method != 'POST':
        return JsonResponse({'error': 'Only POST requests allowed'}, status=405)

    if not _authorized(request):
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    try:
        pipeline = YouTubeLLMPipeline(task_key=task_key)
        if not pipeline.config:
            return JsonResponse({'error': f'Invalid task key: {task_key}'}, status=400)
        pipeline.run_pipeline()

        if len(pipeline.processed_video_ids) == 0:
            return JsonResponse({'status': 'warning', 'message': 'Pipeline executed but no videos were processed'}, status=200)

        return JsonResponse({
            'status': 'success',
            'task': task_key,
            'message': 'Pipeline execution completed',
            'processed_video_count': len(pipeline.processed_video_ids),
        })

    except Exception as e:
        logging.error(f"Pipeline error: {str(e)}")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    

@csrf_exempt
def slack_alert(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Only POST requests allowed'}, status=405)

    if not _authorized(request):
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    try:
        # SAFE JSON PARSING
        if not request.body:
            data = {}
        else:
            data = json.loads(request.body.decode("utf-8"))

        message = data.get('message', 'Test alert from Queuei')
        status = data.get('status', 'INFO')
        job_name = data.get('job_name', 'Test Job')
        extra_data = data.get('extra_data', {})

        send_slack_alert(message, status, job_name, extra_data)

        return JsonResponse({
            'status': 'success',
            'message': 'Slack alert sent successfully'
        })

    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON body'}, status=400)

    except Exception as e:
        logging.error(f"Slack alert error: {str(e)}")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    

def video_page(request, video_id):
    return render(request, "video_page.html", {
        "video_id": video_id
    })

