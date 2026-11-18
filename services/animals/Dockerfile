# The animals service. Build from this folder:  docker build -t animals services/animals

# A specific Python release on Debian bookworm, never `latest`, so a rebuild
# next month gets the same interpreter. "slim" leaves out compilers and docs.
FROM python:3.13.9-slim-bookworm

# No .pyc files in the image, log lines reach `docker logs` straight away, and
# pip keeps no download cache in the layer.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first, on their own: this layer is rebuilt only when
# requirements.txt changes, not on every code change.
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Then the code, file by file. No `COPY . .`: only what the service runs goes
# in, so tests, caches and any stray .env on the build machine stay out.
COPY app.py config.py cors.py db.py migrate.py sample_animals.py security.py entrypoint.sh ./
COPY animals/ animals/
COPY migrations/ migrations/

# Run as an ordinary user, not root, so a flaw in the app cannot rewrite the
# image's files. The code stays owned by root and is only readable to it.
RUN useradd --create-home --uid 10001 app
USER app

EXPOSE 8000

# Migrations, then sample animals, then the web server; see entrypoint.sh.
# No secret is set anywhere in this file: DATABASE_URL and the rest arrive as
# environment variables when the container starts.
ENTRYPOINT ["sh", "entrypoint.sh"]
