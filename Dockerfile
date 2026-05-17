FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY api api
COPY edge edge
COPY rules rules
COPY telemetry telemetry
COPY events events
COPY evidence evidence
COPY spatial spatial
COPY replay replay
COPY migrations migrations
COPY alembic.ini alembic.ini
COPY examples examples
COPY configs configs
COPY runtime_settings.py runtime_settings.py
RUN pip install --no-cache-dir -e .

EXPOSE 8080
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8080"]
