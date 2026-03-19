# Deployment Guide

> [繁體中文版](deployment-zh.md)

## Required IAM Permissions for Deployer

| Service | Permission | Purpose |
|---------|-----------|---------|
| CloudFormation | `cloudformation:*` | SAM deploy create/update stack |
| S3 | `s3:*` on SAM bucket | SAM artifact upload |
| Lambda | `lambda:*` | Create/update Lambda functions |
| DynamoDB | `dynamodb:*` on `geo-content` | Create table, CRUD |
| IAM | `iam:CreateRole`, `iam:AttachRolePolicy`, `iam:PassRole` | Lambda execution role |
| CloudFront | `cloudfront:*Distribution*`, `cloudfront:CreateInvalidation` | Distribution management |
| CloudFront | `cloudfront:*Function*` | CFF management |
| CloudFront | `cloudfront:*OriginAccessControl*` | OAC management |
| Bedrock AgentCore | `bedrock-agentcore:*` | AgentCore deploy/invoke |

## AgentCore Agent

```bash
agentcore deploy
```

Deploys the GEO agent to Bedrock AgentCore (us-east-1). The Agent ARN is written to `.bedrock_agentcore.yaml`; Lambdas need this ARN to trigger agent-based GEO content generation.

## Edge Serving Infrastructure

Architecture: CloudFront OAC + Lambda Function URL (SigV4 authentication).

### Deploy

```bash
sam build -t infra/template.yaml
sam deploy -t infra/template.yaml
```

`samconfig.toml` includes default parameters. For first-time deployment or custom parameters:

```bash
sam deploy -t infra/template.yaml \
  --stack-name geo-backend \
  --region us-east-1 \
  --resolve-s3 \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
    AgentRuntimeArn=<AGENT_ARN> \
    DefaultOriginHost=www.setn.com \
    CloudFrontDistributionArn=arn:aws:cloudfront::<ACCOUNT>:distribution/<DIST_ID> \
    SetupCfOrigin=true \
    CffArn=arn:aws:cloudfront::<ACCOUNT>:function/geo-bot-router-oac
```

Resources created:
- Lambda Function URL (`AuthType: AWS_IAM`)
- CloudFront OAC (SigV4 signing)
- CloudFront → Lambda invoke permission (all distributions in account)
- `geo-content-handler` Lambda — serves GEO content
- `geo-content-generator` Lambda — async AgentCore invocation
- `geo-content-storage` Lambda — agent writes to DDB
- DynamoDB table `geo-content` (skip with `CreateTable=false`)

### SAM Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `TableName` | `geo-content` | DynamoDB table name |
| `AgentRuntimeArn` | (empty) | AgentCore Runtime ARN |
| `DefaultOriginHost` | (empty) | Origin site domain (e.g., `www.setn.com`) |
| `OriginVerifySecret` | `geo-agent-cf-origin-2026` | Defense-in-depth verification header |
| `CloudFrontDistributionArn` | (empty) | CF distribution ARN |
| `CreateTable` | `true` | Whether to create DDB table (set `false` for multi-tenant sharing) |
| `SetupCfOrigin` | `false` | Auto-configure existing CF distribution's origin |
| `CffArn` | (empty) | CFF ARN to associate |
| `CffBehaviorPath` | `*` | Cache behavior path for CFF association |

### SAM S3 Hash Collision

SAM occasionally skips Lambda updates due to unchanged S3 hashes. Update directly:

```bash
# Package all files in infra/lambda/ (all three Lambdas share the same package)
cd infra/lambda && zip -r /tmp/lambda.zip . && cd ../..

# Update each Lambda
aws lambda update-function-code --function-name geo-content-handler --zip-file fileb:///tmp/lambda.zip
aws lambda update-function-code --function-name geo-content-generator --zip-file fileb:///tmp/lambda.zip
aws lambda update-function-code --function-name geo-content-storage --zip-file fileb:///tmp/lambda.zip
```

### CloudFront Function

CFF `geo-bot-router-oac` (`infra/cloudfront-function/geo-router-oac.js`) handles:
1. AI bot User-Agent detection (GPTBot, ClaudeBot, etc.)
2. Setting `x-original-host` header (for multi-tenant routing)
3. Switching origin to `geo-lambda-origin` (Lambda Function URL)

Update CFF:
```bash
# Get ETag
aws cloudfront describe-function --name geo-bot-router-oac --query 'ETag' --output text

# Update
aws cloudfront update-function \
  --name geo-bot-router-oac \
  --if-match <ETAG> \
  --function-config Comment="GEO bot router (OAC)",Runtime=cloudfront-js-2.0 \
  --function-code fileb://infra/cloudfront-function/geo-router-oac.js

# Publish
aws cloudfront publish-function \
  --name geo-bot-router-oac \
  --if-match <NEW_ETAG>
```

### Multi-Site Deployment (Shared DynamoDB)

DDB key format is `{host}#{path}[?query]`, natively supporting multi-tenancy. Multiple sites share a single DDB table.

#### Scenario 1: New CloudFront Distribution

```bash
# Step 1: Deploy Lambda backend
sam deploy --stack-name geo-backend-site \
  -t infra/template.yaml \
  --parameter-overrides \
    TableName=geo-content \
    DefaultOriginHost=www.example.com

# Step 2: Create CloudFront distribution
sam deploy --stack-name geo-cf-site \
  -t infra/cloudfront-distribution.yaml \
  --parameter-overrides \
    OriginDomain=www.example.com \
    GeoFunctionUrlDomain=<FunctionUrl domain from Step 1> \
    GeoOacId=<OacId from Step 1>
```

#### Scenario 2: Existing CloudFront Distribution

```bash
sam deploy --stack-name geo-backend-site \
  -t infra/template.yaml \
  --parameter-overrides \
    TableName=geo-content \
    CreateTable=false \
    DefaultOriginHost=www.example.com \
    CloudFrontDistributionArn=arn:aws:cloudfront::<ACCOUNT>:distribution/<DIST_ID> \
    SetupCfOrigin=true \
    CffArn=arn:aws:cloudfront::<ACCOUNT>:function/geo-bot-router-oac
```

`SetupCfOrigin=true` automatically adds `geo-lambda-origin` origin + OAC + CFF to the existing distribution.

#### Adding More Sites (Shared DDB Table)

For the second site onward, set `CreateTable=false`:

```bash
sam deploy --stack-name geo-backend-linetoday \
  -t infra/template.yaml \
  --parameter-overrides \
    TableName=geo-content \
    CreateTable=false \
    DefaultOriginHost=today.line.me \
    CloudFrontDistributionArn=arn:aws:cloudfront::<ACCOUNT>:distribution/<DIST_ID_B> \
    SetupCfOrigin=true \
    CffArn=arn:aws:cloudfront::<ACCOUNT>:function/geo-bot-router-oac
```

## llms.txt Storage

```bash
# 1. Generate draft
agentcore invoke '{"prompt": "Generate llms.txt for news.tvbs.com.tw"}'

# 2. Store after review
aws lambda invoke --function-name geo-content-storage \
  --region us-east-1 \
  --cli-binary-format raw-in-base64-out \
  --payload '{
    "url_path": "/llms.txt",
    "geo_content": "<reviewed llms.txt content>",
    "original_url": "https://example.com",
    "content_type": "text/markdown; charset=utf-8"
  }' /dev/null

# 3. Verify
curl "https://<CF_DOMAIN>/llms.txt?ua=genaibot"
```

## End-to-End Testing

### CloudFront Cache Invalidation

DDB purge (`?purge=true`) only clears DDB records, not CF cache. For immediate effect:

```bash
aws cloudfront create-invalidation \
  --distribution-id <DIST_ID> \
  --paths "/world/3149600"
```

First 1,000 invalidation paths per month are free.

### Test Commands

```bash
# Simulate AI bot
curl "https://<CF_DOMAIN>/world/3149599?ua=genaibot"

# async mode
curl "https://<CF_DOMAIN>/world/3149599?ua=genaibot&mode=async"

# sync mode (~30-40s)
curl "https://<CF_DOMAIN>/world/3149599?ua=genaibot&mode=sync"

# Verify direct Function URL access is blocked
curl "https://<FUNCTION_URL>/world/3149599"  # Should return 403

# llms.txt
curl "https://<CF_DOMAIN>/llms.txt?ua=genaibot"  # text/markdown
curl "https://<CF_DOMAIN>/llms.txt"               # origin site content
```
