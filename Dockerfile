# Stage 1: Base - Install dependencies
FROM python:3.13-slim AS base

LABEL maintainer="fritill.com"

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/py/bin:$PATH"

# Set working directory
WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    postgresql-client \
    gettext \
    libmagic-dev \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy only requirements for better caching
COPY requirements.txt ./

# Create and activate virtual environment
RUN python3 -m venv --system-site-packages /py && \
    /py/bin/pip install --upgrade pip && \
    /py/bin/pip install --no-cache-dir -r /app/requirements.txt

# Stage 2: Runtime - Minimal lightweight image
FROM python:3.13-slim AS runtime

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/py/bin:$PATH"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       libmagic1 \
       curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy necessary files from base
COPY --from=base /py /py
COPY . .

RUN groupadd -g 1000 app && \
    useradd -u 1000 -g 1000 -m -s /bin/bash app

RUN mkdir -p /app/static /app/media /app/staticfiles && \
    chown -R app:app /app/static /app/media /app/staticfiles && \
    chmod -R 775 /app/static /app/media /app/staticfiles

# Switch to non-root user
USER app

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl --fail http://localhost:8000/healthz || exit 1

# Command to run the app
CMD ["bash", "-c", "gunicorn --bind 0.0.0.0:8000 --workers 2 app.wsgi:application --log-level debug"]