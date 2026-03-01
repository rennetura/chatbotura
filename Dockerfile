# ChatBotura Docker Image
FROM python:3.12-slim

WORKDIR /chatbotura

# Install system dependencies if needed (none required for now)
RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Copy entrypoint
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Expose ports for API (8000) and UI (8501)
EXPOSE 8000 8501

# Run entrypoint
ENTRYPOINT ["/entrypoint.sh"]