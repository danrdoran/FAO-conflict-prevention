# Deployment Guide: Food Security Policy Assistant

This guide provides step-by-step instructions for deploying the Food Security Policy Assistant application using Docker and Google Cloud Run.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Project Structure Preparation](#project-structure-preparation)
3. [Docker Configuration Files](#docker-configuration-files)
4. [Local Docker Deployment](#local-docker-deployment)
5. [Google Cloud Run Deployment](#google-cloud-run-deployment)
6. [Managing Secrets](#managing-secrets)
7. [Troubleshooting](#troubleshooting)

---

## Prerequisites

Before proceeding, ensure you have the following installed and configured:

### Local Development
- **Docker Desktop** (v20.10+): [Download Docker](https://docs.docker.com/get-docker/)
- **Python 3.10+** (for local testing)
- **Git** (for version control)

### Google Cloud Deployment
- **Google Cloud SDK (gcloud CLI)**: [Install gcloud](https://cloud.google.com/sdk/docs/install)
- **Google Cloud Account** with billing enabled
- **Google Cloud Project** created

### Verify Installations

```bash
# Check Docker
docker --version

# Check gcloud CLI
gcloud --version

# Authenticate with Google Cloud
gcloud auth login
```

---

## Project Structure Preparation

Your project should have the following structure after adding the deployment files:

```
FAO-CONFLICT-PREVENTION/
├── .dockerignore          # NEW - Docker ignore file
├── .gcloudignore          # NEW - Cloud Run ignore file
├── .streamlit/            # NEW - Streamlit configuration
│   └── config.toml
├── Dockerfile             # NEW - Docker build instructions
├── .gitignore
├── requirements.txt       # Updated if needed
├── app/
│   ├── streamlit_app_info.py
│   └── streamlit_app.py
├── data/
│   └── docs/
│       └── pathways_for_peace.pdf
└── src/
    ├── __init__.py
    ├── agents/
    │   ├── __init__.py
    │   └── sdg_agent.py
    ├── catalogs/
    │   └── ag_indicators.yaml
    ├── clients/
    │   ├── __init__.py
    │   ├── fao_sdg_client.py
    │   └── sdg_api.py
    └── rag/
        ├── __init__.py
        └── ag_policy_rag.py
```

---

## Docker Configuration Files

### 1. Dockerfile

Create a `Dockerfile` in the project root directory:

```dockerfile
# =============================================================================
# Dockerfile for Food Security Policy Assistant
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

# Expose port (8080 for Cloud Run, can be overridden)
EXPOSE ${PORT}

# Health check for container orchestration
HEALTHCHECK CMD curl --fail http://localhost:${PORT}/_stcore/health || exit 1

# Run Streamlit application
ENTRYPOINT ["streamlit", "run", "app/streamlit_app.py", \
    "--server.port=8080", \
    "--server.address=0.0.0.0", \
    "--server.enableCORS=false", \
    "--server.enableXsrfProtection=false", \
    "--browser.gatherUsageStats=false"]
```

---

### 2. .dockerignore

Create a `.dockerignore` file in the project root:

```plaintext
# =============================================================================
# .dockerignore - Files to exclude from Docker build context
# =============================================================================

# Virtual environments
.venv/
venv/
env/
ENV/

# Python cache
__pycache__/
*.py[cod]
*$py.class
*.so
.Python

# IDE and editor files
.idea/
.vscode/
*.swp
*.swo
*~

# Git
.git/
.gitignore

# Testing and coverage
.pytest_cache/
.coverage
htmlcov/
.tox/
.nox/

# Build artifacts
*.egg-info/
dist/
build/
eggs/
*.egg

# Environment files (secrets should be passed at runtime)
.env
.env.local
*.env

# Documentation
docs/
*.md
!README.md

# Jupyter notebooks
*.ipynb
.ipynb_checkpoints/

# OS files
.DS_Store
Thumbs.db

# Logs
*.log
logs/

# Local development files
.streamlit/secrets.toml

# Temporary files
tmp/
temp/
*.tmp
```

---

### 3. .gcloudignore

Create a `.gcloudignore` file for Cloud Run deployments:

```plaintext
# =============================================================================
# .gcloudignore - Files to exclude from Cloud Run deployment
# =============================================================================

# Include everything from .dockerignore
#!include:.dockerignore

# Virtual environments
.venv/
venv/
env/

# Git
.git/
.gitignore

# Python cache
__pycache__/
*.py[cod]

# IDE files
.idea/
.vscode/

# Local secrets
.env
.env.local
.streamlit/secrets.toml

# Documentation (optional - remove if you want docs in container)
*.md

# Test files
tests/
*_test.py
test_*.py
```

---

### 4. Streamlit Configuration

Create the `.streamlit/` directory and `config.toml` file:

```bash
mkdir -p .streamlit
```

Create `.streamlit/config.toml`:

```toml
[server]
headless = true
enableCORS = false
enableXsrfProtection = false
port = 8080
address = "0.0.0.0"

[browser]
gatherUsageStats = false
serverAddress = "0.0.0.0"

[theme]
primaryColor = "#1f77b4"
backgroundColor = "#ffffff"
secondaryBackgroundColor = "#f0f4f8"
textColor = "#262730"
font = "sans serif"
```

---

### 5. Updated requirements.txt

Ensure your `requirements.txt` includes all necessary dependencies:

```plaintext
# =============================================================================
# requirements.txt - Python dependencies for Food Security Policy Assistant
# =============================================================================

# Web framework
streamlit>=1.28.0

# Data processing
pandas>=2.0.0
numpy>=1.24.0

# HTTP requests
requests>=2.31.0

# Visualization
matplotlib>=3.7.0

# YAML parsing
pyyaml>=6.0

# OpenAI API
openai>=1.0.0

# Environment variables
python-dotenv>=1.0.0

# RAG components (adjust based on your ag_policy_rag.py implementation)
# Uncomment if using these libraries:
# langchain>=0.1.0
# chromadb>=0.4.0
# sentence-transformers>=2.2.0
# pypdf>=3.0.0

# PDF processing (if needed)
# PyMuPDF>=1.23.0
```

---

## Local Docker Deployment

### Step 1: Build the Docker Image

Navigate to your project root and build the image:

```bash
cd FAO-CONFLICT-PREVENTION

# Build the Docker image
docker build -t fao-conflict-prevention:latest .
```

### Step 2: Run Locally (Without Secrets)

For testing without the OpenAI API:

```bash
docker run -p 8080:8080 fao-conflict-prevention:latest
```

### Step 3: Run Locally (With Secrets)

Pass your OpenAI API key as an environment variable:

```bash
docker run -p 8080:8080 \
    -e OPENAI_API_KEY="your-openai-api-key-here" \
    fao-conflict-prevention:latest
```

### Step 4: Access the Application

Open your browser and navigate to:

```
http://localhost:8080
```

### Step 5: Verify Health Check

```bash
curl http://localhost:8080/_stcore/health
```

---

## Google Cloud Run Deployment

### Step 1: Set Up Google Cloud Project

```bash
# Set your project ID
export GCP_PROJECT="your-gcp-project-id"
export GCP_REGION="us-central1"  # Choose your preferred region
export SERVICE_NAME="fao-conflict-prevention"

# Set the active project
gcloud config set project $GCP_PROJECT

# Enable required APIs
gcloud services enable cloudbuild.googleapis.com
gcloud services enable run.googleapis.com
gcloud services enable artifactregistry.googleapis.com
gcloud services enable secretmanager.googleapis.com
```

### Step 2: Create Artifact Registry Repository

```bash
# Create a Docker repository in Artifact Registry
gcloud artifacts repositories create streamlit-apps \
    --repository-format=docker \
    --location=$GCP_REGION \
    --description="Docker repository for Streamlit applications"

# Configure Docker to authenticate with Artifact Registry
gcloud auth configure-docker ${GCP_REGION}-docker.pkg.dev
```

### Step 3: Store Secrets in Secret Manager

```bash
# Create a secret for the OpenAI API key
echo -n "your-openai-api-key-here" | \
    gcloud secrets create openai-api-key \
    --data-file=- \
    --replication-policy="automatic"

# Grant Cloud Run access to the secret
gcloud secrets add-iam-policy-binding openai-api-key \
    --member="serviceAccount:${GCP_PROJECT}@appspot.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor"
```

### Step 4: Build and Push the Docker Image

**Option A: Build locally and push**

```bash
# Build the image for linux/amd64 (required for Cloud Run)
docker build --platform linux/amd64 \
    -t ${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT}/streamlit-apps/${SERVICE_NAME}:latest \
    .

# Push to Artifact Registry
docker push ${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT}/streamlit-apps/${SERVICE_NAME}:latest
```

**Option B: Build using Cloud Build (recommended)**

```bash
# Submit build to Cloud Build
gcloud builds submit \
    --tag ${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT}/streamlit-apps/${SERVICE_NAME}:latest \
    --project=$GCP_PROJECT
```

### Step 5: Deploy to Cloud Run

```bash
gcloud run deploy $SERVICE_NAME \
    --image ${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT}/streamlit-apps/${SERVICE_NAME}:latest \
    --platform managed \
    --region $GCP_REGION \
    --allow-unauthenticated \
    --memory 2Gi \
    --cpu 2 \
    --timeout 300 \
    --concurrency 80 \
    --min-instances 0 \
    --max-instances 10 \
    --set-secrets "OPENAI_API_KEY=openai-api-key:latest" \
    --project $GCP_PROJECT
```

### Step 6: Access Your Deployed Application

After deployment, Cloud Run will provide a URL:

```bash
# Get the service URL
gcloud run services describe $SERVICE_NAME \
    --region $GCP_REGION \
    --format="value(status.url)"
```

The URL will be in the format:
```
https://fao-conflict-prevention-XXXXXXXXXX-XX.a.run.app
```

---

## Managing Secrets

### Using Streamlit Secrets (Alternative Method)

If you prefer using Streamlit's secrets management, create a local `.streamlit/secrets.toml` for development:

```toml
# .streamlit/secrets.toml (DO NOT COMMIT TO GIT)
OPENAI_API_KEY = "your-openai-api-key-here"
```

**Important:** Add this file to `.gitignore` and `.dockerignore`.

### Updating Secrets in Cloud Run

To update the OpenAI API key:

```bash
# Update the secret value
echo -n "new-openai-api-key" | \
    gcloud secrets versions add openai-api-key --data-file=-

# Redeploy the service to use the new secret
gcloud run services update $SERVICE_NAME \
    --region $GCP_REGION \
    --set-secrets "OPENAI_API_KEY=openai-api-key:latest"
```

---

## Troubleshooting

### Common Issues and Solutions

#### 1. Container fails to start

**Symptom:** Cloud Run deployment fails or container exits immediately.

**Solution:** Check logs:
```bash
gcloud run services logs read $SERVICE_NAME --region $GCP_REGION --limit 50
```

#### 2. Import errors for `src` modules

**Symptom:** `ModuleNotFoundError: No module named 'agents'`

**Solution:** Ensure `PYTHONPATH` is set in Dockerfile:
```dockerfile
ENV PYTHONPATH=/app/src
```

#### 3. PDF file not found

**Symptom:** `FileNotFoundError` for `pathways_for_peace.pdf`

**Solution:** Verify the file is copied in Dockerfile and paths are correct:
```dockerfile
COPY data/ data/
```

Update path references in `streamlit_app.py` if needed.

#### 4. Memory errors

**Symptom:** Container crashes during PDF processing or RAG indexing.

**Solution:** Increase memory allocation:
```bash
gcloud run services update $SERVICE_NAME \
    --region $GCP_REGION \
    --memory 4Gi
```

#### 5. Cold start timeouts

**Symptom:** First requests timeout.

**Solution:** Increase timeout and set minimum instances:
```bash
gcloud run services update $SERVICE_NAME \
    --region $GCP_REGION \
    --timeout 600 \
    --min-instances 1
```

#### 6. Port binding issues

**Symptom:** `Error: address already in use`

**Solution:** Ensure Streamlit uses the `PORT` environment variable:
```python
# In your app, Cloud Run sets PORT automatically
import os
port = int(os.environ.get("PORT", 8080))
```

### Viewing Logs

```bash
# View recent logs
gcloud run services logs read $SERVICE_NAME --region $GCP_REGION

# Stream logs in real-time
gcloud alpha run services logs tail $SERVICE_NAME --region $GCP_REGION
```

### Redeploying After Changes

```bash
# Rebuild and redeploy
gcloud builds submit \
    --tag ${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT}/streamlit-apps/${SERVICE_NAME}:latest

gcloud run deploy $SERVICE_NAME \
    --image ${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT}/streamlit-apps/${SERVICE_NAME}:latest \
    --region $GCP_REGION
```

---

## Quick Reference: Complete Deployment Script

Save this as `deploy.sh` in your project root:

```bash
#!/bin/bash
# =============================================================================
# deploy.sh - One-click deployment script for Google Cloud Run
# =============================================================================

set -e

# Configuration (update these values)
export GCP_PROJECT="your-gcp-project-id"
export GCP_REGION="us-central1"
export SERVICE_NAME="fao-conflict-prevention"

echo "🚀 Starting deployment to Google Cloud Run..."

# Set project
gcloud config set project $GCP_PROJECT

# Build and submit
echo "📦 Building container image..."
gcloud builds submit \
    --tag ${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT}/streamlit-apps/${SERVICE_NAME}:latest \
    --project=$GCP_PROJECT

# Deploy
echo "🌐 Deploying to Cloud Run..."
gcloud run deploy $SERVICE_NAME \
    --image ${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT}/streamlit-apps/${SERVICE_NAME}:latest \
    --platform managed \
    --region $GCP_REGION \
    --allow-unauthenticated \
    --memory 2Gi \
    --cpu 2 \
    --timeout 300 \
    --set-secrets "OPENAI_API_KEY=openai-api-key:latest" \
    --project $GCP_PROJECT

# Get URL
echo "✅ Deployment complete!"
echo "🔗 Application URL:"
gcloud run services describe $SERVICE_NAME \
    --region $GCP_REGION \
    --format="value(status.url)"
```

Make it executable:
```bash
chmod +x deploy.sh
./deploy.sh
```

---

## Cost Considerations

Google Cloud Run pricing is based on:
- **CPU allocation** during request handling
- **Memory allocation** during request handling
- **Number of requests**

To minimize costs:
- Set `--min-instances 0` to scale to zero when idle
- Use appropriate memory/CPU settings (start with 2Gi/2 CPU)
- Monitor usage in Google Cloud Console

**Free tier includes:**
- 2 million requests per month
- 360,000 GB-seconds of memory
- 180,000 vCPU-seconds

---

## Next Steps

1. Set up **continuous deployment** with Cloud Build triggers
2. Configure a **custom domain** for your application
3. Add **authentication** using Identity-Aware Proxy (IAP)
4. Set up **monitoring and alerting** in Cloud Monitoring

For questions or issues, consult the [Google Cloud Run documentation](https://cloud.google.com/run/docs) or [Streamlit deployment guides](https://docs.streamlit.io/deploy).