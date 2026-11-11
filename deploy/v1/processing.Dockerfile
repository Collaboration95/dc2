FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
ARG SOURCE_SHA
LABEL org.opencontainers.image.revision=$SOURCE_SHA
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_ROOT_USER_ACTION=ignore \
    PIP_DISABLE_PIP_VERSION_CHECK=1 SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates libexpat1 zlib1g \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock ./
RUN python -m pip install --no-cache-dir uv==0.8.17 \
    && uv export --frozen --no-dev --no-emit-project \
       --extra v1-processing -o /tmp/requirements.txt \
    && uv pip install --system --compile-bytecode --require-hashes -r /tmp/requirements.txt \
    && python -m pip uninstall -y uv && rm /tmp/requirements.txt
COPY deploy/v1/global-bundle.pem /opt/rds/global-bundle.pem
COPY contracts ./contracts
COPY delivery ./delivery
COPY runtime_support ./runtime_support
COPY processing ./processing
# Lambda's filesystem is read-only, so bytecode not built here is recompiled on every cold start.
RUN python -m compileall -q -j0 contracts delivery runtime_support processing
COPY deploy/v1/check_runtime.py /opt/check_runtime.py
RUN --network=none python /opt/check_runtime.py lambda-api processing
RUN useradd --create-home --uid 10001 flickpond
USER flickpond
ENTRYPOINT ["python", "-m", "awslambdaric"]
CMD ["processing.lambda_handler.handler"]
