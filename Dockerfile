FROM python:3.10-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src

ENV PYTHONPATH=/app/src \
    PORT=8000

EXPOSE 8000

CMD ["sh", "-c", "uvicorn src.main:create_app --factory --host 0.0.0.0 --port ${PORT}"]
