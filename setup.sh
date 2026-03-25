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
    MISSING="${MISSING}      macOS:  brew install python@3.10\n"
    MISSING="${MISSING}      Linux:  sudo apt install python3.10  (or yum/dnf)\n\n"
fi

if ! command -v node &>/dev/null; then
    MISSING="${MISSING}  - node (>= 20) — required by AgentCore toolkit\n"
    MISSING="${MISSING}      macOS:  brew install node@20\n"
    MISSING="${MISSING}      Linux:  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - && sudo apt install -y nodejs\n"
    MISSING="${MISSING}      Any:    https://nodejs.org/en/download\n\n"
fi

if ! command -v aws &>/dev/null; then
    MISSING="${MISSING}  - aws CLI (v2)\n"
    MISSING="${MISSING}      macOS:  brew install awscli\n"
    MISSING="${MISSING}      Linux:  curl \"https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip\" -o awscliv2.zip && unzip awscliv2.zip && sudo ./aws/install\n"
    MISSING="${MISSING}      Docs:   https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html\n\n"
fi

if ! command -v sam &>/dev/null; then
    MISSING="${MISSING}  - sam CLI — required for Lambda/DDB deployment\n"
    MISSING="${MISSING}      macOS:  brew install aws-sam-cli\n"
    MISSING="${MISSING}      Linux:  pipx install aws-sam-cli  (recommended, isolated env)\n"
    MISSING="${MISSING}              pip install --user aws-sam-cli  (alternative)\n"
    MISSING="${MISSING}      Docs:   https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html\n\n"
fi

if [ -n "$MISSING" ]; then
    echo "Missing required tools:"
    echo ""
    printf "$MISSING"
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
    read -rp "Target origin domain (e.g. www-origin.example.com): " ORIGIN_HOST
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

# CloudFront Distribution
echo ""
echo "CloudFront distribution setup:"
echo "  - Leave blank to CREATE a new distribution automatically"
echo "  - Enter a distribution domain or ID to use an existing one"
echo "    (e.g. d1234abcdef.cloudfront.net or E2ZP7RSVOE6A8D)"
echo ""
read -rp "CloudFront distribution [create new]: " CF_INPUT

CF_DIST_ID=""
CF_DIST_ARN=""
SETUP_CF_ORIGIN="false"
CREATE_DISTRIBUTION="false"
CFF_BEHAVIOR_PATH="*"

if [ -z "$CF_INPUT" ]; then
    # --- Create new distribution via SAM ---
    CREATE_DISTRIBUTION="true"
    echo "  → Will create a new CloudFront distribution for ${ORIGIN_HOST}"
else
    # --- Use existing distribution ---
    # Normalize input: strip protocol, extract ID or domain
    CF_INPUT=$(echo "$CF_INPUT" | sed 's|^https\?://||' | sed 's|/.*||')

    # If it looks like a domain (contains '.'), look up the distribution ID
    if echo "$CF_INPUT" | grep -q '\.'; then
        echo "  Looking up distribution for domain: ${CF_INPUT}..."
        CF_DIST_ID=$(aws cloudfront list-distributions \
            --query "DistributionList.Items[?DomainName=='${CF_INPUT}'].Id | [0]" \
            --output text 2>/dev/null || true)
        if [ -z "$CF_DIST_ID" ] || [ "$CF_DIST_ID" = "None" ]; then
            echo "  ✗ Distribution not found for domain: ${CF_INPUT}"
            echo "    Verify the domain is correct and belongs to this AWS account."
            exit 1
        fi
        echo "  ✓ Found distribution: ${CF_DIST_ID}"
    else
        # Assume it's a distribution ID directly
        CF_DIST_ID="$CF_INPUT"
        # Verify it exists
        echo "  Verifying distribution ${CF_DIST_ID}..."
        if ! aws cloudfront get-distribution --id "$CF_DIST_ID" --query 'Distribution.Id' --output text &>/dev/null; then
            echo "  ✗ Distribution ${CF_DIST_ID} not found in this account."
            exit 1
        fi
        echo "  ✓ Distribution found"
    fi

    CF_DIST_ARN="arn:aws:cloudfront::${AWS_ACCOUNT}:distribution/${CF_DIST_ID}"
    SETUP_CF_ORIGIN="true"

    # --- List behaviors and let user choose which one to attach CFF ---
    echo ""
    echo "  Available cache behaviors:"
    echo ""

    # Default behavior
    DEFAULT_ORIGIN=$(aws cloudfront get-distribution-config --id "$CF_DIST_ID" \
        --query 'DistributionConfig.DefaultCacheBehavior.TargetOriginId' --output text 2>/dev/null)
    echo "    [0] Default (*) → origin: ${DEFAULT_ORIGIN}"

    # Additional behaviors
    BEHAVIOR_COUNT=$(aws cloudfront get-distribution-config --id "$CF_DIST_ID" \
        --query 'DistributionConfig.CacheBehaviors.Quantity' --output text 2>/dev/null)

    if [ "$BEHAVIOR_COUNT" != "0" ] && [ -n "$BEHAVIOR_COUNT" ]; then
        BEHAVIOR_PATHS=$(aws cloudfront get-distribution-config --id "$CF_DIST_ID" \
            --query 'DistributionConfig.CacheBehaviors.Items[*].[PathPattern, TargetOriginId]' \
            --output text 2>/dev/null)
        IDX=1
        while IFS=$'\t' read -r bpath borigin; do
            echo "    [${IDX}] ${bpath} → origin: ${borigin}"
            IDX=$((IDX + 1))
        done <<< "$BEHAVIOR_PATHS"
    fi

    echo ""
    read -rp "  Attach CFF to which behavior? [0 = Default(*)]: " BEHAVIOR_CHOICE
    BEHAVIOR_CHOICE="${BEHAVIOR_CHOICE:-0}"

    if [ "$BEHAVIOR_CHOICE" = "0" ]; then
        CFF_BEHAVIOR_PATH="*"
    else
        # Extract the chosen path pattern
        CFF_BEHAVIOR_PATH=$(aws cloudfront get-distribution-config --id "$CF_DIST_ID" \
            --query "DistributionConfig.CacheBehaviors.Items[$((BEHAVIOR_CHOICE - 1))].PathPattern" \
            --output text 2>/dev/null)
        if [ -z "$CFF_BEHAVIOR_PATH" ] || [ "$CFF_BEHAVIOR_PATH" = "None" ]; then
            echo "  ⚠ Invalid choice, using Default (*)"
            CFF_BEHAVIOR_PATH="*"
        fi
    fi
    echo "  → CFF will be attached to: ${CFF_BEHAVIOR_PATH}"
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
if [ "$CREATE_DISTRIBUTION" = "true" ]; then
    echo "  CF Distribution: <will create new>"
else
    echo "  CF Dist ID:     ${CF_DIST_ID}"
    echo "  CFF Behavior:   ${CFF_BEHAVIOR_PATH}"
fi
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

if [ "$CREATE_DISTRIBUTION" = "true" ]; then
    PARAM_OVERRIDES="${PARAM_OVERRIDES} CreateDistribution=\\\"true\\\""
elif [ -n "$CF_DIST_ID" ]; then
    PARAM_OVERRIDES="${PARAM_OVERRIDES} CloudFrontDistributionArn=\\\"${CF_DIST_ARN}\\\" SetupCfOrigin=\\\"${SETUP_CF_ORIGIN}\\\" CffArn=\\\"arn:aws:cloudfront::${AWS_ACCOUNT}:function/geo-bot-router-oac\\\" CffBehaviorPath=\\\"${CFF_BEHAVIOR_PATH}\\\""
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
# Step 4: Generate .bedrock_agentcore.yaml
# ----------------------------------------------------------
echo ""
echo "==> Generating .bedrock_agentcore.yaml..."

AGENT_NAME="geoagent"
ENTRYPOINT="$(pwd)/src/main.py"
SOURCE_PATH="$(pwd)/src"

# Detect platform and ensure uv is available for direct_code_deploy
PLATFORM="linux/arm64"
DEPLOY_TYPE="direct_code_deploy"

if ! command -v uv &>/dev/null; then
    echo "==> Installing uv (required for AgentCore direct code deploy)..."
    curl -LsSf https://astral.sh/uv/install.sh | sh 2>&1 | tail -1
    # Source uv into current shell
    if [ -f "$HOME/.local/bin/env" ]; then
        source "$HOME/.local/bin/env"
    elif [ -f "$HOME/.cargo/env" ]; then
        source "$HOME/.cargo/env"
    fi
    export PATH="$HOME/.local/bin:$PATH"
    if command -v uv &>/dev/null; then
        echo "  ✓ uv installed ($(uv --version))"
    else
        echo "  ⚠ uv installation failed. Install manually: https://docs.astral.sh/uv/getting-started/installation/"
        echo "    Then re-run ./setup.sh"
        exit 1
    fi
else
    echo "  ✓ uv found ($(uv --version))"
fi

cat > .bedrock_agentcore.yaml <<EOF
default_agent: ${AGENT_NAME}
agents:
  ${AGENT_NAME}:
    name: ${AGENT_NAME}
    language: python
    node_version: '20'
    entrypoint: ${ENTRYPOINT}
    deployment_type: ${DEPLOY_TYPE}
    runtime_type: PYTHON_3_10
    platform: ${PLATFORM}
    container_runtime: null
    source_path: ${SOURCE_PATH}
    aws:
      execution_role: null
      execution_role_auto_create: true
      account: "${AWS_ACCOUNT}"
      region: ${AWS_REGION}
      ecr_repository: null
      ecr_auto_create: true
      s3_path: null
      s3_auto_create: true
      network_configuration:
        network_mode: PUBLIC
        network_mode_config: null
      protocol_configuration:
        server_protocol: HTTP
      observability:
        enabled: true
      lifecycle_configuration:
        idle_runtime_session_timeout: null
        max_lifetime: null
    bedrock_agentcore:
      agent_id: null
      agent_arn: null
      agent_session_id: null
    codebuild:
      project_name: null
      execution_role: null
      source_bucket: null
    memory:
      mode: STM_ONLY
      memory_id: null
      memory_arn: null
      memory_name: ${AGENT_NAME}_mem
      event_expiry_days: 30
      first_invoke_memory_check_done: false
      was_created_by_toolkit: true
    identity:
      credential_providers: []
      workload: null
    aws_jwt:
      enabled: false
      audiences: []
      signing_algorithm: ES384
      issuer_url: null
      duration_seconds: 300
    authorizer_configuration: null
    request_header_configuration: null
    oauth_configuration: null
    api_key_env_var_name: null
    api_key_credential_provider_name: null
    is_generated_by_agentcore_create: false
EOF

echo "  ✓ .bedrock_agentcore.yaml created (agent: ${AGENT_NAME}, deploy: ${DEPLOY_TYPE})"

# ----------------------------------------------------------
# Step 5: Deploy AgentCore + Infrastructure
# ----------------------------------------------------------
echo ""
echo "Ready to deploy to AWS:"
echo "  1. AgentCore agent (Bedrock AgentCore)"
echo "  2. Infrastructure (Lambda + DDB + OAC + CloudFront)"
echo ""
read -rp "Deploy now? [Y/n]: " DEPLOY_CONFIRM
DEPLOY_CONFIRM="${DEPLOY_CONFIRM:-Y}"
if [[ ! "$DEPLOY_CONFIRM" =~ ^[Yy] ]]; then
    echo ""
    echo "Setup complete (no deploy). To deploy later:"
    echo "  source .venv/bin/activate"
    echo "  agentcore deploy"
    echo "  sam build -t infra/template.yaml"
    echo "  sam deploy -t infra/template.yaml"
    exit 0
fi

echo ""
echo "==> [5/6] Deploying GEO Agent to AgentCore..."
source .venv/bin/activate
agentcore deploy

# Extract Agent Runtime ARN from config
AGENT_ARN=$(grep 'agent_arn:' .bedrock_agentcore.yaml | head -1 | awk '{print $2}')
if [ -z "$AGENT_ARN" ] || [ "$AGENT_ARN" = "null" ]; then
    echo "  ⚠ Could not extract AgentRuntimeArn from .bedrock_agentcore.yaml"
    echo "    Run 'agentcore deploy' manually, then update samconfig.toml with the ARN."
    exit 1
fi
echo "  ✓ Agent deployed: ${AGENT_ARN}"

# Update samconfig.toml with AgentRuntimeArn
sed -i.bak "s|parameter_overrides = \"|parameter_overrides = \"AgentRuntimeArn=\\\\\"${AGENT_ARN}\\\\\" |" samconfig.toml
rm -f samconfig.toml.bak
echo "  ✓ samconfig.toml updated with AgentRuntimeArn"

echo ""
echo "==> [6/6] Deploying infrastructure (Lambda + DDB + OAC)..."
sam build -t infra/template.yaml
sam deploy -t infra/template.yaml --no-confirm-changeset

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║  Deployment complete!                            ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# Show outputs
echo "--- Stack Outputs ---"
aws cloudformation describe-stacks \
    --stack-name geo-backend \
    --region "${AWS_REGION}" \
    --query "Stacks[0].Outputs[*].[OutputKey,OutputValue]" \
    --output table 2>/dev/null || true

echo ""
echo "Test with:"
echo "  source .venv/bin/activate"
echo "  agentcore invoke \"What tools do you have?\""
echo ""
if [ "$CREATE_DISTRIBUTION" = "true" ]; then
    echo "  # Get CF distribution domain from stack outputs above, then:"
    echo "  curl \"https://<CF_DOMAIN>/some-path?ua=genaibot&mode=sync\""
fi
echo ""
echo "  See docs/deployment.md for adding more sites."
echo ""
