FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends zlib1g \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock ./
RUN python -m pip install --no-cache-dir uv==0.8.17 \
    && uv export --frozen --no-dev --extra legacy --no-emit-project -o /tmp/requirements.txt \
    && uv pip install --system --require-hashes -r /tmp/requirements.txt \
    && python -m pip uninstall -y uv \
    && rm /tmp/requirements.txt
# Media contains no Processing metadata, worker code or inherited application DB.
COPY media ./media
COPY contracts ./contracts
COPY delivery ./delivery
COPY runtime_support ./runtime_support
COPY legacy ./legacy
RUN python -m pip install --no-cache-dir --no-deps . \
    && useradd --system --create-home --uid 10001 flickpond
USER flickpond
EXPOSE 8000
CMD ["uvicorn", "legacy.media_peer.app:app", "--host", "0.0.0.0", "--port", "8000"]
