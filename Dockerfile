FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN python -m pip install --no-cache-dir uv==0.8.17 \
    && uv export --frozen --no-dev --extra legacy --no-emit-project -o /tmp/requirements.txt \
    && uv pip install --system --require-hashes -r /tmp/requirements.txt \
    && python -m pip uninstall -y uv \
    && rm /tmp/requirements.txt
COPY app ./app
COPY alembic.ini ./
COPY migrations ./migrations

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg librsvg2-2 libexpat1 zlib1g \
    && dpkg --compare-versions "$(dpkg-query -W -f='${Version}' librsvg2-2)" \
        ge 2.60.0+dfsg-1+deb13u1 \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --no-cache-dir --no-deps .

# Drop root for the runtime. The install above needs it to write into the
# system site-packages; nothing after it does. /app deliberately stays owned by
# root and read-only to this user -- the process reads its own code and never
# writes it, and PYTHONDONTWRITEBYTECODE stops Python trying to drop .pyc files
# beside it. Uploads spool to /tmp, which stays writable, and binding port 8000
# needs no privilege. Both the api and worker services run from this image, so
# both drop root together.
RUN useradd --system --create-home --uid 10001 flickpond
USER flickpond

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]

