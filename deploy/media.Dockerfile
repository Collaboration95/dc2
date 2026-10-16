FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN python -m pip install --no-cache-dir uv==0.8.17 \
    && uv export --frozen --no-dev --no-emit-project -o /tmp/requirements.txt \
    && uv pip install --system --require-hashes -r /tmp/requirements.txt \
    && python -m pip uninstall -y uv \
    && rm /tmp/requirements.txt
# Media contains no Processing metadata, worker code or inherited application DB.
COPY media ./media
COPY contracts ./contracts
COPY delivery ./delivery
COPY runtime_support ./runtime_support
RUN python -m pip install --no-cache-dir --no-deps . \
    && useradd --system --create-home --uid 10001 flickpond
USER flickpond
EXPOSE 8000
CMD ["uvicorn", "media.main:app", "--host", "0.0.0.0", "--port", "8000"]
