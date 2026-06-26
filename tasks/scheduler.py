import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

_scheduler = BackgroundScheduler(timezone='UTC')


def run_pipeline_job(task_key, cron_job_id):
    from tasks.script_custom.youtube_llm_pipeline import YouTubeLLMPipeline
    from tasks.models import CronJob
    from django.utils import timezone
    logging.info(f"Cron: starting pipeline for task_key={task_key}")
    try:
        pipeline = YouTubeLLMPipeline(task_key=task_key)
        pipeline.run_pipeline()
        CronJob.objects.filter(id=cron_job_id).update(last_run_at=timezone.now())
        logging.info(f"Cron: finished pipeline for task_key={task_key}")
    except Exception as e:
        logging.error(f"Cron: pipeline error for task_key={task_key}: {e}")


def run_endpoint_job(endpoint_url, cron_job_id):
    from tasks.models import CronJob
    from django.utils import timezone
    from django.test import RequestFactory
    from django.urls import resolve, Resolver404
    logging.info(f"Cron: dispatching internal endpoint {endpoint_url}")
    try:
        factory = RequestFactory()
        request = factory.post(endpoint_url)
        try:
            view_func, args, kwargs = resolve(endpoint_url)
        except Resolver404:
            logging.error(f"Cron: no URL match for {endpoint_url}")
            return
        response = view_func(request, *args, **kwargs)
        CronJob.objects.filter(id=cron_job_id).update(last_run_at=timezone.now())
        logging.info(f"Cron: endpoint {endpoint_url} → status {response.status_code}")
    except Exception as e:
        logging.error(f"Cron: endpoint error for {endpoint_url}: {e}")


def load_jobs():
    """Reload all active CronJob records into the scheduler."""
    from tasks.models import CronJob
    _scheduler.remove_all_jobs()
    loaded = []
    try:
        for job in CronJob.objects.filter(is_active=True):
            parts = job.cron_expression.strip().split()
            if len(parts) != 5:
                logging.warning(f"Cron: invalid expression for job '{job.name}': {job.cron_expression}")
                continue
            minute, hour, day, month, day_of_week = parts
            if job.job_type == 'endpoint':
                fn = run_endpoint_job
                args = [job.endpoint_url, job.id]
            else:
                fn = run_pipeline_job
                args = [job.task_key, job.id]
            _scheduler.add_job(
                fn,
                CronTrigger(
                    minute=minute, hour=hour, day=day,
                    month=month, day_of_week=day_of_week, timezone='UTC',
                ),
                args=args,
                id=f'cron_job_{job.id}',
                replace_existing=True,
                misfire_grace_time=300,
            )
            loaded.append(job.name)
        logging.info(f"Cron: {len(loaded)} active jobs loaded: {loaded}")
    except Exception as e:
        logging.warning(f"Cron: could not load jobs (DB may not be ready): {e}")


def start():
    load_jobs()
    if not _scheduler.running:
        _scheduler.start()
        logging.info("Cron: scheduler started")
