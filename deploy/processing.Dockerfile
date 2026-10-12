FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

# Processing installs without importing or packaging Media Management's app/.
COPY pyproject.toml ./
COPY processing ./processing
RUN python -m pip install --no-cache-dir . \
    && useradd --system --create-home --uid 10001 flickpond
USER flickpond

EXPOSE 8000
CMD ["uvicorn", "processing.main:app", "--host", "0.0.0.0", "--port", "8000"]
