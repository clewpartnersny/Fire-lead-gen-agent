FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

COPY sectors ./sectors

# Persist the SQLite state DBs and CSV fallbacks across restarts
VOLUME ["/app/data", "/app/out"]

CMD ["fire-leadgen", "run-all"]
