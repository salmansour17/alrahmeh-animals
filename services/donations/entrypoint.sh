#!/bin/sh
# Start-up of the donations service inside its container.
#
# Each step runs once, before the web server starts its workers. `set -e` stops
# the script at the first failing step, so if the migrations fail the web server
# never starts on a schema it does not expect, and the container exits with an
# error that the platform reports.
set -e

python migrate.py

# PORT is read through config.py, so a malformed value falls back to 8000 here
# exactly as it does in development.
PORT="$(python -c 'from config import load_config; print(load_config().port)')"

# exec replaces this shell with gunicorn, so the container's stop signal reaches
# gunicorn directly and it can finish requests in flight before exiting.
# One worker process with four threads (WEB_WORKERS, WEB_THREADS). One
# process, so the rate limits and the name cache, which live in memory, are
# shared by every request instead of split between processes (a limit of 5
# would really be 10 across two). Four threads still serve requests side by
# side while each waits on the database or another service. The cost: a
# CPU-heavy request (resizing a photo) slows the others, and if the process
# dies, every request in flight dies with it. The access log goes to stdout,
# one line per request: method, path, status and time taken in milliseconds.
exec gunicorn \
    --bind "0.0.0.0:${PORT}" \
    --workers "${WEB_WORKERS:-1}" \
    --threads "${WEB_THREADS:-4}" \
    --access-logfile - \
    --access-logformat '%(m)s %(U)s %(s)s %(M)sms' \
    "app:create_app()"
