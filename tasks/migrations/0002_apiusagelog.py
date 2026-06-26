from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('records', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='ApiUsageLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField()),
                ('model', models.CharField(max_length=100)),
                ('request_type', models.CharField(choices=[('generate', 'Generate'), ('embed', 'Embed')], max_length=10)),
                ('prompt_tokens', models.IntegerField(default=0)),
                ('output_tokens', models.IntegerField(default=0)),
                ('total_tokens', models.IntegerField(default=0)),
                ('source', models.CharField(choices=[('intel_chat', 'Intel Chat'), ('pipeline', 'Pipeline')], default='intel_chat', max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'ordering': ['-created_at'],
                'indexes': [models.Index(fields=['date'], name='records_api_date_idx')],
            },
        ),
    ]
