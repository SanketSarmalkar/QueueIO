#!/bin/sh

set -e
echo "--- 🛠️ SYSTEM INITIALIZATION ---"
echo "Running database migrations..."
python manage.py migrate --no-input
echo "Starting Gunicorn server..."
exec gunicorn core.wsgi:application --bind 0.0.0.0:8000 --workers 2