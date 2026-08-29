"""Create DashboardFeed and seed one example markdown feed + its daily cron."""

from django.db import migrations, models

EXAMPLE_KEY = "ai_brief"
EXAMPLE_CRON = "45 3 * * *"  # 09:15 IST (UTC+5:30), just after the stock refresh
EXAMPLE_PROMPT = (
    "You are a research analyst. Write a concise daily briefing (markdown, with a "
    "short intro then 4-6 bullet points) on the current state and near-term outlook "
    "of the global AI industry — models, funding, regulation, notable launches. "
    "Keep it under 250 words. Use ## headings and **bold** for key terms."
)


def seed_example(apps, schema_editor):
    DashboardFeed = apps.get_model("tasks", "DashboardFeed")
    CronJob = apps.get_model("tasks", "CronJob")
    DashboardFeed.objects.update_or_create(
        key=EXAMPLE_KEY,
        defaults={
            "title": "AI Daily Brief",
            "icon": "fa-newspaper",
            "prompt": EXAMPLE_PROMPT,
            "render_type": "markdown",
            "ai_model": "",
            "is_active": True,
        },
    )
    CronJob.objects.update_or_create(
        name="AI Daily Brief",
        defaults={
            "job_type": "endpoint",
            "endpoint_url": f"/tasks/feed/{EXAMPLE_KEY}/",
            "task_key": "",
            "cron_expression": EXAMPLE_CRON,
            "is_active": True,
        },
    )


def unseed_example(apps, schema_editor):
    apps.get_model("tasks", "CronJob").objects.filter(name="AI Daily Brief").delete()
    apps.get_model("tasks", "DashboardFeed").objects.filter(key=EXAMPLE_KEY).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0005_stock_refresh_cronjob"),
    ]

    operations = [
        migrations.CreateModel(
            name="DashboardFeed",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.SlugField(help_text="URL-safe id used in the cron endpoint, e.g. market_brief", unique=True)),
                ("title", models.CharField(help_text="Tab label shown in the dashboard", max_length=100)),
                ("icon", models.CharField(default="fa-newspaper", help_text="Font Awesome class, e.g. fa-newspaper", max_length=50)),
                ("prompt", models.TextField(help_text="Prompt sent to the LLM on each scheduled run.")),
                ("render_type", models.CharField(choices=[("markdown", "Markdown"), ("table", "Table")], default="markdown", help_text="markdown = prose; table = LLM returns a JSON array of rows", max_length=20)),
                ("ai_model", models.CharField(blank=True, default="", help_text="Optional model override; blank uses the global AI_MODEL", max_length=60)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.RunPython(seed_example, unseed_example),
    ]
