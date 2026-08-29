from django.db import models

class TaskConfiguration(models.Model):
    task_key = models.CharField(max_length=50, unique=True, help_text="e.g., summarize, sentiment_analysis")
    display_name = models.CharField(max_length=100)
    prompt_template = models.TextField(help_text="The prompt sent to Gemini. Use {transcript} as placeholder.")
    target_collection = models.CharField(max_length=50, default="mass_records")
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.display_name

class GlobalSetting(models.Model):
    key = models.CharField(max_length=100, unique=True)
    value = models.TextField()
    description = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return self.key


class CronJob(models.Model):
    JOB_TYPE_PIPELINE = 'pipeline'
    JOB_TYPE_ENDPOINT = 'endpoint'
    JOB_TYPE_CHOICES = [('pipeline', 'Pipeline'), ('endpoint', 'Endpoint')]

    name = models.CharField(max_length=100)
    job_type = models.CharField(max_length=20, choices=JOB_TYPE_CHOICES, default='pipeline')
    task_key = models.CharField(max_length=50, blank=True, help_text="Must match an active TaskConfiguration key")
    endpoint_url = models.CharField(max_length=500, blank=True, default='', help_text="Relative path, e.g. /tasks/alert/")
    cron_expression = models.CharField(max_length=100, help_text="5-part cron: minute hour day month weekday")
    is_active = models.BooleanField(default=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class DashboardFeed(models.Model):
    """A generic scheduled-LLM feed rendered as its own dashboard tab.

    A superuser defines the prompt + how to render it; a CronJob (endpoint type)
    hitting /tasks/feed/<key>/ refreshes it on a schedule. The latest response is
    stored in MongoDB (`dashboard_feeds`) and injected into the dashboard the same
    way `stacks`/`stocks` data is.
    """
    RENDER_MARKDOWN = 'markdown'
    RENDER_TABLE = 'table'
    RENDER_CHOICES = [(RENDER_MARKDOWN, 'Markdown'), (RENDER_TABLE, 'Table')]

    key = models.SlugField(max_length=50, unique=True,
                           help_text="URL-safe id used in the cron endpoint, e.g. market_brief")
    title = models.CharField(max_length=100, help_text="Tab label shown in the dashboard")
    icon = models.CharField(max_length=50, default='fa-newspaper',
                            help_text="Font Awesome class, e.g. fa-newspaper")
    prompt = models.TextField(help_text="Prompt sent to the LLM on each scheduled run.")
    render_type = models.CharField(max_length=20, choices=RENDER_CHOICES, default=RENDER_MARKDOWN,
                                   help_text="markdown = prose; table = LLM returns a JSON array of rows")
    ai_model = models.CharField(max_length=60, blank=True, default='',
                                help_text="Optional model override; blank uses the global AI_MODEL")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class TranscriptCache(models.Model):
    video_id = models.CharField(max_length=50, unique=True, db_index=True)
    transcript = models.TextField()
    cached_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.video_id