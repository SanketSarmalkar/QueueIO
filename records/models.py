from django.db import models
from django.contrib.auth.models import User


class Bookmark(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='bookmarks')
    report_id = models.CharField(max_length=24)
    title = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'report_id')
        ordering = ['-created_at']


class ApiUsageLog(models.Model):
    REQUEST_TYPES = [('generate', 'Generate'), ('embed', 'Embed')]
    SOURCES = [('intel_chat', 'Intel Chat'), ('pipeline', 'Pipeline')]

    date = models.DateField()
    model = models.CharField(max_length=100)
    request_type = models.CharField(max_length=10, choices=REQUEST_TYPES)
    prompt_tokens = models.IntegerField(default=0)
    output_tokens = models.IntegerField(default=0)
    total_tokens = models.IntegerField(default=0)
    source = models.CharField(max_length=20, choices=SOURCES, default='intel_chat')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['date'])]
