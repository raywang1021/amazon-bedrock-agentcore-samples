# 部署指南

> [English](deployment.md)

## 部署者所需 IAM 權限

| 服務 | 權限 | 用途 |
|------|------|------|
| CloudFormation | `cloudformation:*` | SAM deploy 建立/更新 stack |
| S3 | `s3:*` on SAM bucket | SAM 上傳 artifact |
| Lambda | `lambda:*` | 建立/更新 Lambda 函數 |
| DynamoDB | `dynamodb:*` on `geo-content` | 建立 table、CRUD |
| IAM | `iam:CreateRole`, `iam:AttachRolePolicy`, `iam:PassRole` | Lambda execution role |
| CloudFront | `cloudfront:*Distribution*`, `cloudfront:CreateInvalidation` | distribution 管理 |
| CloudFront | `cloudfront:*Function*` | CFF 管理 |
| CloudFront | `cloudfront:*OriginAccessControl*` | OAC 管理 |
| Bedrock AgentCore | `bedrock-agentcore:*` | AgentCore deploy/invoke |

## AgentCore Agent

```bash
agentcore deploy
```

部署 GEO agent 到 Bedrock AgentCore（us-east-1）。Agent ARN 寫入 `.bedrock_agentcore.yaml`，Lambda 需要此 ARN 觸發 agent 產生 GEO 內容。

## Edge Serving Infrastructure

架構：CloudFront OAC + Lambda Function URL（SigV4 認證），零額外成本。

### 部署

```bash
sam build -t infra/template.yaml
sam deploy -t infra/template.yaml
```

`samconfig.toml` 已包含預設參數。首次部署或需自訂參數時：

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
建立的資源：
- Lambda Function URL（`AuthType: AWS_IAM`）
- CloudFront OAC（SigV4 簽署）
- CloudFront → Lambda invoke permission（帳號內所有 distribution）
- `geo-content-handler` Lambda — 服務 GEO 內容
- `geo-content-generator` Lambda — 非同步呼叫 AgentCore
- `geo-content-storage` Lambda — Agent 寫入 DDB
- DynamoDB table `geo-content`（可透過 `CreateTable=false` 跳過）

### SAM 參數

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `TableName` | `geo-content` | DynamoDB table 名稱 |
| `AgentRuntimeArn` | （空） | AgentCore Runtime ARN |
| `DefaultOriginHost` | （空） | 原始站台 domain（如 `www.setn.com`） |
| `OriginVerifySecret` | `geo-agent-cf-origin-2026` | Defense-in-depth 驗證 header |
| `CloudFrontDistributionArn` | （空） | CF distribution ARN |
| `CreateTable` | `true` | 是否建立 DDB table（多租戶共用時設 `false`） |
| `SetupCfOrigin` | `false` | 自動設定既有 CF distribution 的 origin |
| `CffArn` | （空） | 要關聯的 CFF ARN |
| `CffBehaviorPath` | `*` | CFF 關聯的 cache behavior path |

### SAM S3 Hash Collision

SAM 偶爾會因 S3 hash 未變而跳過 Lambda 更新。此時直接更新：

```bash
# 打包 infra/lambda/ 所有檔案（三個 Lambda 共用同一 package）
cd infra/lambda && zip -r /tmp/lambda.zip . && cd ../..

# 逐一更新
aws lambda update-function-code --function-name geo-content-handler --zip-file fileb:///tmp/lambda.zip
aws lambda update-function-code --function-name geo-content-generator --zip-file fileb:///tmp/lambda.zip
aws lambda update-function-code --function-name geo-content-storage --zip-file fileb:///tmp/lambda.zip
```

### CloudFront Function

CFF `geo-bot-router-oac`（`infra/cloudfront-function/geo-router-oac.js`）負責：
1. 偵測 AI bot User-Agent（GPTBot、ClaudeBot 等）
2. 設定 `x-original-host` header（多租戶路由用）
3. 切換 origin 到 `geo-lambda-origin`（Lambda Function URL）

更新 CFF：
```bash
# 取得 ETag
aws cloudfront describe-function --name geo-bot-router-oac --query 'ETag' --output text

# 更新
aws cloudfront update-function \
  --name geo-bot-router-oac \
  --if-match <ETAG> \
  --function-config Comment="GEO bot router (OAC)",Runtime=cloudfront-js-2.0 \
  --function-code fileb://infra/cloudfront-function/geo-router-oac.js

# 發布
aws cloudfront publish-function \
  --name geo-bot-router-oac \
  --if-match <NEW_ETAG>
```

### 新增站台（多租戶）

Backend（Lambda + DynamoDB + OAC）只需部署一次。Lambda permission 使用 wildcard `distribution/*`，同帳號下所有 CloudFront distribution 都能呼叫 handler，不需要改 Lambda。

新增站台只需要現有 backend 的 Function URL domain 和 OAC ID：

```bash
# 1. 取得現有 Function URL domain 和 OAC ID
aws lambda get-function-url-config \
  --function-name geo-content-handler --region us-east-1 \
  --query 'FunctionUrl' --output text

aws cloudfront list-origin-access-controls \
  --query "OriginAccessControlList.Items[?Name=='geo-lambda-oac'].Id" \
  --output text

# 2. 一行指令部署新的 CloudFront distribution
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

這會建立：
- 新的 CloudFront distribution，default origin 指向 `<ORIGIN_DOMAIN>`
- `geo-lambda-origin` 指向現有的 `geo-content-handler` Function URL + OAC
- 專屬的 CFF 做 AI bot 偵測和 origin 切換

DDB key 格式 `{host}#{path}` 天然隔離各 distribution 的資料，不需要改 DDB table。

範例 — 新增 `24h.pchome.com.tw`：

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

#### 掛載到既有 CloudFront Distribution

如果你已經有 CloudFront distribution，想加上 GEO 功能（而非建立新的），在 backend template 使用 `SetupCfOrigin=true`：

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

這會自動在既有 distribution 加上 `geo-lambda-origin` origin + OAC + CFF。

## llms.txt 存入

```bash
# 1. 產出草稿
agentcore invoke '{"prompt": "幫 news.tvbs.com.tw 產生 llms.txt"}'

# 2. 審核後存入 DDB
aws lambda invoke --function-name geo-content-storage \
  --region us-east-1 \
  --cli-binary-format raw-in-base64-out \
  --payload '{
    "url_path": "/llms.txt",
    "geo_content": "<審核後的 llms.txt 內容>",
    "original_url": "https://example.com",
    "content_type": "text/markdown; charset=utf-8"
  }' /dev/null

# 3. 驗證
curl "https://<CF_DOMAIN>/llms.txt?ua=genaibot"
```

## 端到端測試

### CloudFront 快取清除

DDB purge（`?purge=true`）只清 DDB 記錄，不清 CF 快取。若需立即生效：

```bash
aws cloudfront create-invalidation \
  --distribution-id <DIST_ID> \
  --paths "/world/3149600"
```

每月前 1,000 個 invalidation path 免費。

### 測試指令

```bash
# 模擬 AI bot
curl "https://<CF_DOMAIN>/world/3149599?ua=genaibot"

# async 模式
curl "https://<CF_DOMAIN>/world/3149599?ua=genaibot&mode=async"

# sync 模式（~30-40s）
curl "https://<CF_DOMAIN>/world/3149599?ua=genaibot&mode=sync"

# 驗證 Function URL 直接存取被擋
curl "https://<FUNCTION_URL>/world/3149599"  # 應回 403

# llms.txt
curl "https://<CF_DOMAIN>/llms.txt?ua=genaibot"  # text/markdown
curl "https://<CF_DOMAIN>/llms.txt"               # 原站內容
```
