FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY core ./core
COPY tests ./tests
COPY alembic.ini ./

RUN pip install --no-cache-dir .[dev]

EXPOSE 8000

CMD ["uvicorn", "core.main:app", "--host", "0.0.0.0", "--port", "8000"]
