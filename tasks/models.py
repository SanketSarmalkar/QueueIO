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