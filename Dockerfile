# Dockerfile for TrackTrade FastAPI app
FROM python:3.12-slim

# Set work directory
WORKDIR /app

# Install system dependencies (if needed)
RUN apt-get update && apt-get install -y build-essential && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Expose port
EXPOSE ${PORT}

# Start the app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "${PORT}"]

