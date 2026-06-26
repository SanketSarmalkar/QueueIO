import sys
from django.apps import AppConfig

_SKIP_CMDS = {'migrate', 'makemigrations', 'collectstatic', 'test', 'shell', 'createsuperuser', 'check', 'flush'}


class TasksConfig(AppConfig):
    name = 'tasks'

    def ready(self):
        if len(sys.argv) > 1 and sys.argv[1] in _SKIP_CMDS:
            return
        try:
            from tasks.scheduler import start
            start()
        except Exception as e:
            import logging
            logging.warning(f"Could not start scheduler: {e}")
