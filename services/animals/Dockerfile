# The animals service. Build from this folder:  docker build -t animals services/animals

# A specific Python release on Debian bookworm, never `latest`. The tag says
# which release; the digest after @ fixes the exact bytes, so even a re-pushed
# tag cannot change what we build on. It is the digest of the multi-platform
# index, so the same line builds on amd64 (Azure) and arm64 (some laptops).
# "slim" leaves out compilers and docs. Dependabot proposes updates to both.
FROM python:3.13.9-slim-bookworm@sha256:b685a4fa58bb19d1814d78a1ec0f0208f351452724f78b20212c984d6e124a34

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

# The git commit this image is built from, passed by the pipeline with
# --build-arg GIT_SHA=<sha>, kept as an environment variable so GET /health can
# report it ("dev" when built without it). It comes this late on purpose: every
# commit has a new value, and Docker rebuilds every layer after the one where a
# value changes, so placed earlier it would reinstall all the dependencies on
# every build.
ARG GIT_SHA=dev
ENV GIT_SHA=${GIT_SHA}

# Run as an ordinary user, not root, so a flaw in the app cannot rewrite the
# image's files. The code stays owned by root and is only readable to it.
RUN useradd --create-home --uid 10001 app
USER app

EXPOSE 8000

# Migrations, then sample animals, then the web server; see entrypoint.sh.
# No secret is set anywhere in this file: DATABASE_URL and the rest arrive as
# environment variables when the container starts.
ENTRYPOINT ["sh", "entrypoint.sh"]
