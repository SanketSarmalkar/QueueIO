# Use the official Python 3.14 slim image
FROM python:3.14-slim

# 1. Set environment variables
# Prevents Python from writing pyc files to disc
ENV PYTHONDONTWRITEBYTECODE=1
# Prevents Python from buffering stdout and stderr
ENV PYTHONUNBUFFERED=1

# 2. Set work directory
WORKDIR /app

# 3. Install system dependencies for Postgres and general build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 4. Install Python dependencies
# Copy only requirements first to leverage Docker cache
COPY requirements.txt /app/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 5. Copy project files
COPY . /app/

# 6. Expose the Django port
EXPOSE 8000

# 7. Run migrations and start server
# Note: In production, use 'gunicorn'. For now, we use runserver.
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]