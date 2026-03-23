#!/usr/bin/env bash
set -e

# ============================================================
# GEO Agent — Interactive Setup
# ============================================================

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║          GEO Agent — Project Setup               ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# ----------------------------------------------------------
# Step 0: Prerequisite checks
# ----------------------------------------------------------
echo "--- Checking prerequisites ---"
echo ""

MISSING=""

if ! command -v python3 &>/dev/null; then
    MISSING="${MISSING}  - python3 (>= 3.10)\n"
fi

if ! command -v node &>/dev/null; then
    MISSING="${MISSING}  - node (>= 20) — required by AgentCore toolkit\n"
fi

if ! command -v aws &>/dev/null; then
    MISSING="${MISSING}  - aws CLI (v2)\n"
fi

if ! command -v sam &>/dev/null; then
    MISSING="${MISSING}  - sam CLI — required for Lambda/DDB deployment\n"
fi

if [ -n "$MISSING" ]; then
    echo "Missing required tools:"
    echo ""
    printf "$MISSING"
    echo ""
    echo "Install them and re-run ./setup.sh"
    exit 1
fi

# Version checks
PYTHON_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null)
NODE_VER=$(node -v 2>/dev/null | sed 's/^v//' | cut -d. -f1)

echo "  python3  $PYTHON_VER"
echo "  node     $(node -v 2>/dev/null)"
echo "  aws      $(aws --version 2>/dev/null | awk '{print $1}' | cut -d/ -f2)"
echo "  sam      $(sam --version 2>/dev/null | awk '{print $NF}')"
echo ""

if [ "$(echo "$PYTHON_VER < 3.10" | bc 2>/dev/null)" = "1" ]; then
    echo "  ⚠ Python >= 3.10 required (found $PYTHON_VER)"
    exit 1
fi

if [ -n "$NODE_VER" ] && [ "$NODE_VER" -lt 20 ] 2>/dev/null; then
    echo "  ⚠ Node >= 20 required (found v$NODE_VER)"
    exit 1
fi

echo "  ✓ All prerequisites met"
echo ""

# ----------------------------------------------------------
# Step 1: Collect configuration
# ----------------------------------------------------------
echo "--- Configuration ---"
echo ""

# AWS Region
read -rp "AWS Region [us-east-1]: " AWS_REGION
AWS_REGION="${AWS_REGION:-us-east-1}"

# Origin host (required)
while true; do
    read -rp "Target origin domain (e.g. news.tvbs.com.tw): " ORIGIN_HOST
    if [ -n "$ORIGIN_HOST" ]; then
        # Strip protocol prefix if user pasted a full URL
        ORIGIN_HOST=$(echo "$ORIGIN_HOST" | sed 's|^https\?://||' | sed 's|/.*||')
        break
    fi
    echo "  ⚠ Origin domain is required."
done

# AWS Account ID
DEFAULT_ACCOUNT=$(aws sts get-caller-identity --query Account --output text 2>/dev/null || true)
if [ -n "$DEFAULT_ACCOUNT" ]; then
    read -rp "AWS Account ID [$DEFAULT_ACCOUNT]: " AWS_ACCOUNT
    AWS_ACCOUNT="${AWS_ACCOUNT:-$DEFAULT_ACCOUNT}"
else
    while true; do
        read -rp "AWS Account ID: " AWS_ACCOUNT
        if [ -n "$AWS_ACCOUNT" ]; then break; fi
        echo "  ⚠ Account ID is required."
    done
fi

# CloudFront Distribution ID (optional)
echo ""
echo "If you already have a CloudFront distribution for this site,"
echo "enter its ID (e.g. E2ZP7RSVOE6A8D). Leave blank to skip."
read -rp "CloudFront Distribution ID []: " CF_DIST_ID

# Build ARN and SetupCfOrigin flag
if [ -n "$CF_DIST_ID" ]; then
    CF_DIST_ARN="arn:aws:cloudfront::${AWS_ACCOUNT}:distribution/${CF_DIST_ID}"
    SETUP_CF_ORIGIN="true"
else
    CF_DIST_ARN=""
    SETUP_CF_ORIGIN="false"
fi

# Origin verify secret
DEFAULT_SECRET="geo-agent-cf-origin-$(date +%Y)"
read -rp "Origin verify secret [$DEFAULT_SECRET]: " ORIGIN_SECRET
ORIGIN_SECRET="${ORIGIN_SECRET:-$DEFAULT_SECRET}"

# DynamoDB table name
read -rp "DynamoDB table name [geo-content]: " TABLE_NAME
TABLE_NAME="${TABLE_NAME:-geo-content}"

echo ""
echo "--- Summary ---"
echo "  Region:         $AWS_REGION"
echo "  Origin:         $ORIGIN_HOST"
echo "  Account:        $AWS_ACCOUNT"
echo "  CF Dist ID:     ${CF_DIST_ID:-<none — will create later>}"
echo "  Table:          $TABLE_NAME"
echo "  Verify Secret:  $ORIGIN_SECRET"
echo ""
read -rp "Proceed? [Y/n]: " CONFIRM
CONFIRM="${CONFIRM:-Y}"
if [[ ! "$CONFIRM" =~ ^[Yy] ]]; then
    echo "Aborted."
    exit 0
fi

# ----------------------------------------------------------
# Step 2: Generate samconfig.toml
# ----------------------------------------------------------
echo ""
echo "==> Generating samconfig.toml..."

PARAM_OVERRIDES="TableName=\\\"${TABLE_NAME}\\\" DefaultOriginHost=\\\"${ORIGIN_HOST}\\\" OriginVerifySecret=\\\"${ORIGIN_SECRET}\\\""

if [ -n "$CF_DIST_ID" ]; then
    PARAM_OVERRIDES="${PARAM_OVERRIDES} CloudFrontDistributionArn=\\\"${CF_DIST_ARN}\\\" SetupCfOrigin=\\\"${SETUP_CF_ORIGIN}\\\" CffArn=\\\"arn:aws:cloudfront::${AWS_ACCOUNT}:function/geo-bot-router-oac\\\" CffBehaviorPath=\\\"*\\\""
fi

cat > samconfig.toml <<EOF
version = 0.1

[default.deploy.parameters]
stack_name = "geo-backend"
resolve_s3 = true
s3_prefix = "geo-backend"
region = "${AWS_REGION}"
confirm_changeset = true
capabilities = "CAPABILITY_IAM"
parameter_overrides = "${PARAM_OVERRIDES}"
image_repositories = []

[default.global.parameters]
region = "${AWS_REGION}"
EOF

echo "  ✓ samconfig.toml created"

# ----------------------------------------------------------
# Step 3: Python virtual environment
# ----------------------------------------------------------
echo ""
echo "==> Creating virtual environment..."
python3 -m venv .venv

echo "==> Installing dependencies..."
.venv/bin/pip install -e . 2>&1 | tail -1

# Fix chardet/charset_normalizer conflict
if .venv/bin/pip show chardet > /dev/null 2>&1; then
    echo "==> Fixing chardet/charset_normalizer conflict..."
    .venv/bin/pip uninstall chardet -y > /dev/null 2>&1
fi

# ----------------------------------------------------------
# Done
# ----------------------------------------------------------
echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║  Setup complete!                                 ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""
echo "Next steps:"
echo ""
echo "  1. source .venv/bin/activate"
echo "  2. agentcore configure        # AWS credentials + AgentCore setup"
echo "  3. agentcore deploy           # Deploy agent → get Runtime ARN"
echo "  4. sam build -t infra/template.yaml"
echo "  5. sam deploy -t infra/template.yaml"
echo ""
if [ -z "$CF_DIST_ID" ]; then
    echo "  Note: You skipped CloudFront distribution setup."
    echo "  After creating one, re-run setup or edit samconfig.toml"
    echo "  to add CloudFrontDistributionArn and SetupCfOrigin=true."
    echo ""
fi
echo "  See docs/deployment.md for full deployment guide."
echo ""
