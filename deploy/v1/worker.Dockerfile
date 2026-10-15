FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
ARG SOURCE_SHA
LABEL org.opencontainers.image.revision=$SOURCE_SHA
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock ./
RUN python -m pip install --no-cache-dir uv==0.8.17 \
    && uv export --frozen --no-dev --no-emit-project --extra v1-worker -o /tmp/requirements.txt \
    && uv pip install --system --require-hashes -r /tmp/requirements.txt \
    && python -m pip uninstall -y uv && rm /tmp/requirements.txt
COPY deploy/v1/global-bundle.pem /opt/rds/global-bundle.pem
COPY contracts ./contracts
COPY delivery ./delivery
COPY runtime_support ./runtime_support
COPY processing ./processing
COPY media_engine ./media_engine
COPY deploy/v1/check_runtime.py /opt/check_runtime.py
RUN --network=none python /opt/check_runtime.py finite-worker worker
RUN useradd --system --create-home --uid 10001 flickpond
USER flickpond
ENTRYPOINT ["python", "-m", "processing.v1_worker"]
