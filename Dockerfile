FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

COPY config ./config

# Persist the SQLite state DB and CSV fallback across restarts
VOLUME ["/app/data", "/app/out"]

CMD ["fire-leadgen", "run"]
