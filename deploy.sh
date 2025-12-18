#!/bin/bash
# =============================================================================
# deploy.sh - Deployment script for Google Cloud Run
# Food Security Policy Assistant for Conflict Prevention
# =============================================================================

set -e  # Exit on any error

# =============================================================================
# CONFIGURATION - Update these values before running
# =============================================================================
export GCP_PROJECT="food-sec-confl-policy-tool"      # Your Google Cloud Project ID
export GCP_REGION="us-central1"                # Deployment region
export SERVICE_NAME="fao-conflict-prevention"  # Cloud Run service name
export AR_REPO="streamlit-apps"                # Artifact Registry repository name

# =============================================================================
# Color codes for output
# =============================================================================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# =============================================================================
# Helper functions
# =============================================================================
print_step() {
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}▶ $1${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ WARNING: $1${NC}"
}

print_error() {
    echo -e "${RED}✗ ERROR: $1${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

# =============================================================================
# Validation
# =============================================================================
if [ "$GCP_PROJECT" == "your-gcp-project-id" ]; then
    print_error "Please update GCP_PROJECT in this script before running."
    echo "Edit deploy.sh and set GCP_PROJECT to your Google Cloud Project ID."
    exit 1
fi

# =============================================================================
# Main deployment process
# =============================================================================
echo ""
echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   Food Security Policy Assistant - Cloud Run Deployment    ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Step 1: Set project
print_step "Step 1/6: Setting Google Cloud project"
gcloud config set project $GCP_PROJECT
print_success "Project set to: $GCP_PROJECT"

# Step 2: Enable APIs
print_step "Step 2/6: Enabling required Google Cloud APIs"
gcloud services enable cloudbuild.googleapis.com --quiet
gcloud services enable run.googleapis.com --quiet
gcloud services enable artifactregistry.googleapis.com --quiet
gcloud services enable secretmanager.googleapis.com --quiet
print_success "APIs enabled"

# Step 3: Create Artifact Registry repository (if not exists)
print_step "Step 3/6: Setting up Artifact Registry"
if gcloud artifacts repositories describe $AR_REPO --location=$GCP_REGION &>/dev/null; then
    print_success "Repository '$AR_REPO' already exists"
else
    gcloud artifacts repositories create $AR_REPO \
        --repository-format=docker \
        --location=$GCP_REGION \
        --description="Docker repository for Streamlit applications" \
        --quiet
    print_success "Repository '$AR_REPO' created"
fi

# Configure Docker authentication
gcloud auth configure-docker ${GCP_REGION}-docker.pkg.dev --quiet
print_success "Docker authentication configured"

# Step 4: Build container image
print_step "Step 4/6: Building container image with Cloud Build"
IMAGE_URI="${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT}/${AR_REPO}/${SERVICE_NAME}:latest"

gcloud builds submit \
    --tag $IMAGE_URI \
    --project=$GCP_PROJECT \
    --quiet

print_success "Container image built and pushed: $IMAGE_URI"

# Step 5: Check for secrets
print_step "Step 5/6: Checking secrets configuration"
if gcloud secrets describe openai-api-key --project=$GCP_PROJECT &>/dev/null; then
    print_success "Secret 'openai-api-key' found"
    SECRETS_FLAG="--set-secrets=OPENAI_API_KEY=openai-api-key:latest"
else
    print_warning "Secret 'openai-api-key' not found."
    echo "To add it, run:"
    echo "  echo -n 'your-api-key' | gcloud secrets create openai-api-key --data-file=-"
    SECRETS_FLAG=""
fi

# Step 6: Deploy to Cloud Run
print_step "Step 6/6: Deploying to Cloud Run"
gcloud run deploy $SERVICE_NAME \
    --image $IMAGE_URI \
    --platform managed \
    --region $GCP_REGION \
    --allow-unauthenticated \
    --memory 2Gi \
    --cpu 2 \
    --timeout 300 \
    --concurrency 80 \
    --min-instances 0 \
    --max-instances 10 \
    $SECRETS_FLAG \
    --project $GCP_PROJECT \
    --quiet

# Get and display the service URL
SERVICE_URL=$(gcloud run services describe $SERVICE_NAME \
    --region $GCP_REGION \
    --format="value(status.url)" \
    --project $GCP_PROJECT)

echo ""
echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║              🎉 Deployment Successful! 🎉                  ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "Service Name:  ${BLUE}$SERVICE_NAME${NC}"
echo -e "Region:        ${BLUE}$GCP_REGION${NC}"
echo -e "Project:       ${BLUE}$GCP_PROJECT${NC}"
echo ""
echo -e "🔗 Application URL: ${GREEN}$SERVICE_URL${NC}"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Useful commands:"
echo "  View logs:     gcloud run services logs read $SERVICE_NAME --region $GCP_REGION"
echo "  Update:        ./deploy.sh"
echo "  Delete:        gcloud run services delete $SERVICE_NAME --region $GCP_REGION"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"