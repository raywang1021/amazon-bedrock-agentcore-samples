# 部署指南

## AgentCore Agent

```bash
agentcore deploy
```

部署 GEO agent 到 Bedrock AgentCore（us-east-1）。部署後可用 `agentcore invoke` 呼叫。

Agent ARN 會寫入 `.bedrock_agentcore.yaml`，Lambda 需要這個 ARN 來觸發 agent 產生 GEO 內容。

## Edge Serving Infrastructure

### 1. Backend（DynamoDB + Lambda + Lambda Function URL）

```bash
sam build --template infra/template.yaml
sam deploy --template infra/template.yaml \
  --stack-name geo-backend \
  --region us-east-1 \
  --resolve-s3 \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
    AgentRuntimeArn=<AGENT_ARN> \
    DefaultOriginHost=alb.kgg23.com
```

這會建立：
- DynamoDB table `geo-content`
- `geo-content-handler` Lambda + Function URL（服務 GEO 內容 + 觸發產生）
- `geo-content-generator` Lambda（非同步呼叫 AgentCore 產生 GEO 內容）
- API Gateway endpoint（保留作為 fallback）

### 2. CloudFront Function

方法 A — 透過 AWS CLI 更新：

```bash
# 取得 ETag
aws cloudfront describe-function --name geo-bot-router

# 更新代碼
aws cloudfront update-function \
  --name geo-bot-router \
  --if-match <ETAG> \
  --function-config Comment="Routes AI bot requests to GEO-optimized content origin",Runtime=cloudfront-js-2.0 \
  --function-code fileb://infra/cloudfront-function/geo-router.js

# 發布到 LIVE
aws cloudfront publish-function \
  --name geo-bot-router \
  --if-match <NEW_ETAG>
```

方法 B — 透過 CloudFormation：

```bash
aws cloudformation deploy \
  --template-file infra/cloudfront-function/template.yaml \
  --stack-name geo-cf-function \
  --region us-east-1 \
  --parameter-overrides \
    GeoApiDomain=<LAMBDA_FUNCTION_URL_DOMAIN>
```

方法 C — 手動在 CloudFront console 貼上 `infra/cloudfront-function/geo-router.js` 的內容。

### 3. CloudFront 手動設定

- 將 CF Function `geo-bot-router` 掛到 distribution 的 viewer-request event
- Cache policy 的 cache key 加入 `ua` 和 `mode` querystring
- Origin response timeout 設為 90 秒（配合 sync mode）

### CFF 測試

```bash
# 測試一般使用者（不切換 origin）
aws cloudfront test-function \
  --name geo-bot-router \
  --if-match <ETAG> \
  --stage DEVELOPMENT \
  --event-object fileb://test/cff-test-normal-user.json

# 測試 GPTBot（切換 origin）
aws cloudfront test-function \
  --name geo-bot-router \
  --if-match <ETAG> \
  --stage DEVELOPMENT \
  --event-object fileb://test/cff-test-gptbot.json

# 測試 querystring 模擬
aws cloudfront test-function \
  --name geo-bot-router \
  --if-match <ETAG> \
  --stage DEVELOPMENT \
  --event-object fileb://test/cff-test-querystring.json
```

## 端到端測試

```bash
# 模擬 AI bot（透過 querystring）
curl "https://<CF_DOMAIN>/world/3149599?ua=genaibot"

# async 模式
curl "https://<CF_DOMAIN>/world/3149599?ua=genaibot&mode=async"

# sync 模式（需等待 ~30-40s）
curl "https://<CF_DOMAIN>/world/3149599?ua=genaibot&mode=sync"

# 直接打 Lambda Function URL
curl "https://<FUNCTION_URL>/world/3149599"
```
