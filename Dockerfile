# Dockerfile for TrackTrade FastAPI app
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y build-essential && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Railway define $PORT automaticamente
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port $PORT"]
