# 部署指南

## AgentCore Agent

```bash
agentcore deploy
```

部署 GEO agent 到 Bedrock AgentCore（us-east-1）。部署後可用 `agentcore invoke` 呼叫。

Agent ARN 會寫入 `.bedrock_agentcore.yaml`，Lambda 需要這個 ARN 來觸發 agent 產生 GEO 內容。

## Edge Serving Infrastructure

### 1. Backend（VPC + ALB + Lambda + DynamoDB）

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
- VPC + 2 public subnets（如果沒提供 VpcId）
- ALB + Security Group（只允許 CloudFront managed prefix list）
- `geo-content-handler` Lambda（ALB target，唯一入口）
- `geo-content-generator` Lambda（非同步呼叫 AgentCore）
- DynamoDB table `geo-content`

使用現有 VPC：

```bash
sam deploy --template infra/template.yaml \
  --stack-name geo-backend \
  --region us-east-1 \
  --resolve-s3 \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
    AgentRuntimeArn=<AGENT_ARN> \
    DefaultOriginHost=alb.kgg23.com \
    VpcId=vpc-xxxxxxxx \
    SubnetIds=subnet-aaa,subnet-bbb
```

查詢 CloudFront managed prefix list ID（如果要手動指定）：

```bash
aws ec2 describe-managed-prefix-lists \
  --filters "Name=prefix-list-name,Values=com.amazonaws.global.cloudfront.origin-facing" \
  --query 'PrefixLists[0].PrefixListId' --output text
```

部署完成後，記下 `AlbDnsName` output，用於設定 CloudFront distribution 的 ALB origin。

### 2. CloudFront Distribution 設定

在 CloudFront distribution 中手動設定 ALB origin：

1. 新增 origin：
   - Origin domain: `<AlbDnsName>`（SAM deploy output）
   - Origin ID: `geo-alb-origin`
   - Protocol: HTTP only
   - Port: 80
   - Origin read timeout: 90 秒
   - Custom header: `x-origin-verify` = `geo-agent-cf-origin-2026`

2. 將 CF Function `geo-bot-router` 掛到 distribution 的 viewer-request event

3. Cache policy 的 cache key 加入 `ua` 和 `mode` querystring

### 3. CloudFront Function

CFF 使用 `cf.selectRequestOriginById('geo-alb-origin')` 切換 origin，不需要在 CFF 中設定 ALB domain。

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

方法 B — 手動在 CloudFront console 貼上 `infra/cloudfront-function/geo-router.js` 的內容。

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

# 直接打 ALB（非 CloudFront IP 會被 SG 擋）
curl "http://<ALB_DNS>/world/3149599"
```
