# 部署指南

## 部署者所需 IAM 權限

部署本系統需要以下 IAM 權限，請確認部署者的 IAM user/role 具備：

| 服務 | 權限 | 用途 |
|------|------|------|
| CloudFormation | `cloudformation:*` | SAM deploy 建立/更新 stack |
| S3 | `s3:*` on SAM bucket | SAM 上傳 artifact |
| Lambda | `lambda:*` | 建立/更新 Lambda 函數 |
| DynamoDB | `dynamodb:*` on `geo-content` | 建立 table、CRUD |
| IAM | `iam:CreateRole`, `iam:AttachRolePolicy`, `iam:PassRole` | Lambda execution role |
| CloudFront | `cloudfront:CreateDistribution`, `cloudfront:UpdateDistribution` | 建立/更新 distribution |
| CloudFront | `cloudfront:CreateInvalidation` | 清除 CF 快取（purge 後需搭配使用） |
| CloudFront | `cloudfront:*Function*` | 建立/更新/發布 CFF |
| CloudFront | `cloudfront:*OriginAccessControl*` | OAC 模式 |
| EC2 | `ec2:*` | ALB 模式：VPC、Subnet、SG |
| ELB | `elasticloadbalancing:*` | ALB 模式 |
| Bedrock AgentCore | `bedrock-agentcore:*` | AgentCore deploy/invoke |

最小權限原則：
- 只用 OAC 模式 → 不需 EC2、ELB 權限
- 只用 ALB 模式 → 不需 `cloudfront:*OriginAccessControl*`
- 不需手動清 CF 快取 → 不需 `cloudfront:CreateInvalidation`

## AgentCore Agent

```bash
agentcore deploy
```

部署 GEO agent 到 Bedrock AgentCore（us-east-1）。部署後可用 `agentcore invoke` 呼叫。

Agent ARN 會寫入 `.bedrock_agentcore.yaml`，Lambda 需要這個 ARN 來觸發 agent 產生 GEO 內容。

## Edge Serving Infrastructure

SAM template 支援兩種 origin 模式，透過 `OriginMode` 參數選擇：

| 模式 | 說明 | 成本 | 安全機制 |
|------|------|------|---------|
| `alb`（預設）| ALB + Security Group + VPC | ALB 費用 + VPC | SG (CF prefix list) + `x-origin-verify` header |
| `oac` | Lambda Function URL + CloudFront OAC | 零額外成本 | SigV4 簽署（IAM auth） |

### 模式 A：ALB（預設）

```bash
sam build --template infra/template.yaml
sam deploy --template infra/template.yaml \
  --stack-name geo-backend \
  --region us-east-1 \
  --resolve-s3 \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
    OriginMode=alb \
    AgentRuntimeArn=<AGENT_ARN> \
    DefaultOriginHost=<CF_DOMAIN>
```

建立的資源：
- VPC + 2 public subnets（如果沒提供 VpcId）
- ALB + Security Group（只允許 CloudFront managed prefix list）
- `geo-content-handler` Lambda（ALB target）
- `geo-content-generator` Lambda（非同步 AgentCore invoke）
- DynamoDB table `geo-content`

使用現有 VPC：
```bash
sam deploy ... \
  --parameter-overrides \
    OriginMode=alb \
    VpcId=vpc-xxxxxxxx \
    SubnetIds=subnet-aaa,subnet-bbb \
    ...
```

CloudFront origin 設定：
1. Origin domain: `<AlbDnsName>`（SAM output）
2. Origin ID: `geo-alb-origin`
3. Protocol: HTTP only, Port: 80
4. Custom header: `x-origin-verify` = `geo-agent-cf-origin-2026`

### 模式 B：OAC（推薦）

```bash
sam build --template infra/template.yaml
sam deploy --template infra/template.yaml \
  --stack-name geo-backend \
  --region us-east-1 \
  --resolve-s3 \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
    OriginMode=oac \
    AgentRuntimeArn=<AGENT_ARN> \
    DefaultOriginHost=<CF_DOMAIN> \
    CloudFrontDistributionArn=arn:aws:cloudfront::<ACCOUNT>:distribution/<DIST_ID>
```

建立的資源：
- Lambda Function URL（`AuthType: AWS_IAM`）
- CloudFront OAC（SigV4 簽署）
- CloudFront → Lambda invoke permission
- `geo-content-handler` Lambda
- `geo-content-generator` Lambda
- DynamoDB table `geo-content`

不建立 VPC、ALB、Security Group。

CloudFront origin 設定：
1. Origin domain: `<FunctionUrl>` 的 domain 部分（SAM output，去掉 `https://`）
2. Origin ID: `geo-lambda-origin`
3. OAC: 選擇 `geo-lambda-oac`（SAM output `OacId`）
4. Custom header: `x-origin-verify` = `geo-agent-cf-origin-2026`（defense-in-depth）

### CloudFront Function

兩個 CFF 分別對應兩種 origin 模式：

| CFF | 檔案 | Origin ID |
|-----|------|-----------|
| `geo-bot-router` | `infra/cloudfront-function/geo-router.js` | `geo-alb-origin` |
| `geo-bot-router-oac` | `infra/cloudfront-function/geo-router-oac.js` | `geo-lambda-origin` |

部署時根據 origin 模式選擇對應的 CFF 關聯到 CloudFront distribution。

更新 CFF（以 ALB 模式為例）：
```bash
# 取得 ETag
aws cloudfront describe-function --name geo-bot-router --query 'ETag' --output text

# 更新
aws cloudfront update-function \
  --name geo-bot-router \
  --if-match <ETAG> \
  --function-config Comment="GEO bot router",Runtime=cloudfront-js-2.0 \
  --function-code fileb://infra/cloudfront-function/geo-router.js

# 發布
aws cloudfront publish-function \
  --name geo-bot-router \
  --if-match <NEW_ETAG>
```

OAC 模式同理，將 `geo-bot-router` 替換為 `geo-bot-router-oac`，檔案替換為 `geo-router-oac.js`。

### 模式切換

從 ALB 切換到 OAC（或反向）：
```bash
sam deploy ... --parameter-overrides OriginMode=oac ...
```

CloudFormation 會自動刪除舊模式的資源、建立新模式的資源。切換後需更新 CloudFront distribution 的 origin 設定。

## llms.txt 存入

用 Agent 產出 llms.txt 草稿，經 owner 審核後存入 DDB：

```bash
# 1. 產出草稿
agentcore invoke '{"prompt": "幫 news.tvbs.com.tw 產生 llms.txt"}'

# 2. 審核/編輯內容後，透過 Storage Lambda 存入 DDB
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

DDB purge（`?purge=true`）只清 DDB 記錄，不清 CF 快取。若需立即生效，需搭配 CF invalidation：

```bash
# 清除特定路徑
aws cloudfront create-invalidation \
  --distribution-id <DIST_ID> \
  --paths "/world/3149600"

# 清除全部
aws cloudfront create-invalidation \
  --distribution-id <DIST_ID> \
  --paths "/*"
```

注意：每月前 1,000 個 invalidation path 免費，超過後每個 path $0.005。

### 測試指令

```bash
bash test/e2e_test.sh [CF_DOMAIN] [ALB_DNS]
```

手動測試：
```bash
# 模擬 AI bot
curl "https://<CF_DOMAIN>/world/3149599?ua=genaibot"

# async 模式
curl "https://<CF_DOMAIN>/world/3149599?ua=genaibot&mode=async"

# sync 模式（~30-40s）
curl "https://<CF_DOMAIN>/world/3149599?ua=genaibot&mode=sync"

# 驗證 Function URL 直接存取被擋（OAC 模式）
curl "https://<FUNCTION_URL>/world/3149599"  # 應回 403

# 驗證 ALB 直接存取被擋（ALB 模式）
curl "http://<ALB_DNS>/world/3149599"  # 應 timeout

# llms.txt（bot 拿到 Markdown，一般使用者走原站）
curl "https://<CF_DOMAIN>/llms.txt?ua=genaibot"  # 應回 text/markdown
curl "https://<CF_DOMAIN>/llms.txt"               # 應回原站 404

# OAC 模式測試（使用 OAC distribution domain）
curl "https://<OAC_CF_DOMAIN>/world/3149600?ua=genaibot"  # 應回 GEO 內容
curl "https://<OAC_CF_DOMAIN>/world/3149600"              # 應回原站內容
```
