FROM python:3.11-slim

# System dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose API port
EXPOSE 8000

# Start the FastAPI server (scheduler is embedded inside)
CMD ["uvicorn", "api_server:app", "--host", "0.0.0.0", "--port", "8000"]
