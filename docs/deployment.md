# Deployment Guide

> [繁體中文版](deployment.zh-TW.md)

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

### Adding a New Site (Multi-Tenant)

The backend (Lambda + DynamoDB + OAC) only needs to be deployed once. Lambda permission uses wildcard `distribution/*`, so all CloudFront distributions in the same account can invoke the handler without any Lambda changes.

To add a new site, you only need the Function URL domain and OAC ID from the existing backend:

```bash
# 1. Get existing Function URL domain and OAC ID
aws lambda get-function-url-config \
  --function-name geo-content-handler --region us-east-1 \
  --query 'FunctionUrl' --output text

aws cloudfront list-origin-access-controls \
  --query "OriginAccessControlList.Items[?Name=='geo-lambda-oac'].Id" \
  --output text

# 2. Deploy a new CloudFront distribution (one command)
sam deploy -t infra/cloudfront-distribution.yaml \
  --stack-name geo-cf-<SITE_NAME> \
  --region us-east-1 \
  --resolve-s3 \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
    OriginDomain=<ORIGIN_DOMAIN> \
    GeoFunctionUrlDomain=<FUNCTION_URL_DOMAIN> \
    GeoOacId=<OAC_ID>
```

This creates:
- A new CloudFront distribution with `<ORIGIN_DOMAIN>` as default origin
- `geo-lambda-origin` pointing to the existing `geo-content-handler` Function URL + OAC
- A dedicated CFF for AI bot detection and origin switching

DDB key format `{host}#{path}` naturally isolates data per distribution. No DDB table changes needed.

Example — adding `24h.pchome.com.tw`:

```bash
sam deploy -t infra/cloudfront-distribution.yaml \
  --stack-name geo-cf-pchome \
  --region us-east-1 \
  --resolve-s3 \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
    OriginDomain=24h.pchome.com.tw \
    GeoFunctionUrlDomain=vb2e25fi4mxfcsaiestqooysca0rjfhp.lambda-url.us-east-1.on.aws \
    GeoOacId=E35SJUFLDEE9PJ
```

#### Attaching to an Existing CloudFront Distribution

If you already have a CloudFront distribution and want to add GEO capability to it (instead of creating a new one), use `SetupCfOrigin=true` in the backend template:

```bash
sam deploy --stack-name geo-backend \
  -t infra/template.yaml \
  --parameter-overrides \
    TableName=geo-content \
    CreateTable=false \
    DefaultOriginHost=www.example.com \
    CloudFrontDistributionArn=arn:aws:cloudfront::<ACCOUNT>:distribution/<DIST_ID> \
    SetupCfOrigin=true \
    CffArn=arn:aws:cloudfront::<ACCOUNT>:function/geo-bot-router-oac
```

This automatically adds `geo-lambda-origin` origin + OAC + CFF to the existing distribution.

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
