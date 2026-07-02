"""Celery application for finance-service.

Broker and result backend both point at REDIS_URL (see config.settings). Task
modules are auto-discovered from every INSTALLED_APPS entry's ``tasks`` module.
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("finance_service")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
