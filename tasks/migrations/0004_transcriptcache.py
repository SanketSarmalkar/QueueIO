from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0003_cronjob_job_type_endpoint_url'),
    ]

    operations = [
        migrations.CreateModel(
            name='TranscriptCache',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('video_id', models.CharField(db_index=True, max_length=50, unique=True)),
                ('transcript', models.TextField()),
                ('cached_at', models.DateTimeField(auto_now_add=True)),
            ],
        ),
    ]
