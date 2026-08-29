import sys
import threading
import logging
from django.apps import AppConfig

_SKIP_CMDS = {'migrate', 'makemigrations', 'collectstatic', 'test', 'shell', 'createsuperuser', 'check', 'flush'}


class TasksConfig(AppConfig):
    name = 'tasks'

    def ready(self):
        if len(sys.argv) > 1 and sys.argv[1] in _SKIP_CMDS:
            return
        # Defer scheduler start to after Django is fully initialized so that
        # DB queries in load_jobs() don't trigger the "app initialization" warning.
        threading.Thread(target=self._start_scheduler, daemon=True).start()

    def _start_scheduler(self):
        from django.apps import apps
        import time
        while not apps.ready:
            time.sleep(0.05)
        try:
            from tasks.scheduler import start
            start()
        except Exception as e:
            logging.warning(f"Could not start scheduler: {e}")
