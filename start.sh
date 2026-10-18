#!/usr/bin/env bash
# One image, three roles (forms:AD-26). The Deployment picks one with args;
# each role execs so its process is PID 1 and receives SIGTERM directly.
set -euo pipefail
cd "$(dirname "$0")"

role="${1:-web}"
case "$role" in
  web)
    # Web runs no messaging, so estate:AD-23 does not pin its worker count.
    exec gunicorn -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000 \
      --workers "${WEB_CONCURRENCY:-2}" --timeout 120 app.asgi:application --log-level info
    ;;
  relay)
    exec python manage.py relay
    ;;
  consume)
    exec python manage.py consume
    ;;
  check)
    exec python -S -I app/heartbeat.py "${2:-}"
    ;;
  *)
    echo "usage: start.sh web|relay|consume|check relay|consume" >&2
    exit 2
    ;;
esac
