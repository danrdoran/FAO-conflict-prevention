# =============================================================================
# Dockerfile for Food Security Policy Assistant
# Optimized for Google Cloud Run deployment
# =============================================================================

# Use Python 3.11 slim image for smaller footprint
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PORT=8080

# Set working directory (must not be root for Streamlit 1.10+)
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better Docker layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy Streamlit configuration
COPY .streamlit/ .streamlit/

# Copy application code
COPY app/ app/
COPY src/ src/
COPY data/ data/

# Create directory for RAG index storage
RUN mkdir -p /app/rag_store

# Expose port (8080 for Cloud Run)
EXPOSE ${PORT}

# Health check for container orchestration
HEALTHCHECK CMD curl --fail http://localhost:${PORT}/_stcore/health || exit 1

# Run Streamlit application
# Note: Using the app in the app/ directory
ENTRYPOINT ["streamlit", "run", "app/streamlit_app_docker.py", \
    "--server.port=8080", \
    "--server.address=0.0.0.0", \
    "--server.enableCORS=false", \
    "--server.enableXsrfProtection=false", \
    "--browser.gatherUsageStats=false"]