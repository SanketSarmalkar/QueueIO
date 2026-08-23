"""Seed the daily NASDAQ stock-refresh CronJob.

Creates (idempotently) an endpoint-type job that hits /tasks/stocks_refresh/
every morning. APScheduler runs in UTC, so 09:00 IST == 03:30 UTC -> "30 3 * * *".
Reversing the migration removes the job again.
"""

from django.db import migrations

JOB_NAME = "NASDAQ Stock Refresh"
ENDPOINT = "/tasks/stocks_refresh/"
CRON = "30 3 * * *"  # 09:00 Asia/Kolkata (IST) expressed in UTC


def create_job(apps, schema_editor):
    CronJob = apps.get_model("tasks", "CronJob")
    CronJob.objects.update_or_create(
        name=JOB_NAME,
        defaults={
            "job_type": "endpoint",
            "endpoint_url": ENDPOINT,
            "task_key": "",
            "cron_expression": CRON,
            "is_active": True,
        },
    )


def remove_job(apps, schema_editor):
    CronJob = apps.get_model("tasks", "CronJob")
    CronJob.objects.filter(name=JOB_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0004_transcriptcache"),
    ]

    operations = [
        migrations.RunPython(create_job, remove_job),
    ]
