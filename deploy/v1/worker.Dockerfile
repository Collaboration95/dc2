FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
ARG SOURCE_SHA
LABEL org.opencontainers.image.revision=$SOURCE_SHA
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_ROOT_USER_ACTION=ignore \
    PIP_DISABLE_PIP_VERSION_CHECK=1 SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates libexpat1 \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock ./
RUN python -m pip install --no-cache-dir uv==0.8.17 \
    && uv export --frozen --no-dev --no-emit-project \
       --extra v1-worker -o /tmp/requirements.txt \
    && uv pip install --system --compile-bytecode --require-hashes -r /tmp/requirements.txt \
    && python -m pip uninstall -y uv && rm /tmp/requirements.txt
COPY deploy/v1/global-bundle.pem /opt/rds/global-bundle.pem
COPY contracts ./contracts
COPY delivery ./delivery
COPY runtime_support ./runtime_support
COPY processing ./processing
COPY media_engine ./media_engine
# The same image is the opt-in Lambda short encoder (V2, #93), whose filesystem is read-only:
# bytecode not built here is recompiled on every cold start. Fargate is unaffected.
RUN python -m compileall -q -j0 contracts delivery runtime_support processing media_engine
# Referenced by the template's BootstrapTaskDefinition (ECS entryPoint python /opt/db-bootstrap.py).
# Standalone: it imports neither domain nor an AWS SDK, only asyncpg from the common base.
COPY scripts/aws/v1/bootstrap.py /opt/db-bootstrap.py
COPY deploy/v1/check_runtime.py /opt/check_runtime.py
RUN --network=none python /opt/check_runtime.py finite-worker worker
RUN useradd --create-home --uid 10001 flickpond
USER flickpond
ENTRYPOINT ["python", "-m", "processing.v1_worker"]
