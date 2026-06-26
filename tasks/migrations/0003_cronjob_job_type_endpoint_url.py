from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0002_cronjob'),
    ]

    operations = [
        migrations.AddField(
            model_name='cronjob',
            name='job_type',
            field=models.CharField(
                choices=[('pipeline', 'Pipeline'), ('endpoint', 'Endpoint')],
                default='pipeline',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='cronjob',
            name='endpoint_url',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Relative path, e.g. /tasks/alert/',
                max_length=500,
            ),
        ),
        migrations.AlterField(
            model_name='cronjob',
            name='task_key',
            field=models.CharField(
                blank=True,
                help_text='Must match an active TaskConfiguration key',
                max_length=50,
            ),
        ),
    ]
