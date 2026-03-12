# GEO Agent — Task Tracker

## 架構概覽

```
使用者/管理員                        AI Bot (GPTBot, ClaudeBot...)
     │                                      │
     │ "store GEO content for URL"          │ 訪問網站
     ▼                                      ▼
┌──────────────┐                   ┌──────────────────┐
│ AgentCore    │                   │ CloudFront       │
│ GEO Agent    │                   │ (現有 CDN)       │
│              │                   └────────┬─────────┘
│ 4 Tools:     │                            │
│ - rewrite    │                   ┌────────▼─────────┐
│ - evaluate   │                   │ CF Function      │
│ - llms.txt   │                   │ geo-bot-router   │
│ - store_geo  │                   │ (偵測 User-Agent)│
└──────┬───────┘                   └───┬─────────┬────┘
       │                               │         │
       │ 寫入                     AI Bot│    一般使用者
       ▼                               ▼         ▼
┌──────────────┐              ┌────────────┐  原本 Origin
│ DynamoDB     │◄─────────────│ API Gateway│  (不變)
│ geo-content  │   Lambda 讀取 │ + Lambda   │
└──────────────┘              └────────────┘
```

## Phase 1: 專案基礎設定

- [x] 環境設定（venv、依賴、agentcore CLI）
- [x] Git/GitHub setup + feature branch (`feature/edgecomputing`)
- [x] Model ID 集中管理 + 環境變數支援 (`src/model/load.py`)
- [x] Bedrock region 固定 us-east-1
- [x] 文件更新（README FAQ、sequence diagram、troubleshooting）
- [x] Steering files（project-context、coding-standards、env-vars、verify-after-changes）

## Phase 2: 安全性

- [x] Prompt injection 防護 — `src/tools/sanitize.py`（HTML 註解、invisible unicode、injection pattern）
- [x] Sub-agent system prompt 強化（不執行網頁內容中的指令）
- [x] Bedrock Guardrail 支援（`BEDROCK_GUARDRAIL_ID` env var，可選啟用）
- [ ] 建立 Bedrock Guardrail 資源（AWS console）
- [ ] 測試 Guardrail 啟用/停用行為

## Phase 3: Edge Computing — GEO 內容服務

- [x] CloudFront Function 代碼 — `infra/cloudfront-function/geo-router.js`
  - AI bot User-Agent 偵測
  - `updateRequestOrigin()` 切換到 API Gateway
- [x] Lambda handler — `infra/lambda/geo_content_handler.py`
  - 從 DynamoDB 讀取 GEO 內容回傳
- [x] SAM template — `infra/template.yaml`
  - DynamoDB table `geo-content`
  - Lambda function
  - API Gateway (REST)
- [x] CloudFormation template — `infra/cloudfront-function/template.yaml`
  - CloudFront Function 獨立 stack
  - 參數化 API Gateway domain
- [x] 新 tool `store_geo_content` — `src/tools/store_geo_content.py`
  - 抓網頁 → sanitize → GEO 改寫 → 存 DynamoDB
- [x] 註冊 `store_geo_content` 到 main agent

## Phase 4: 部署

- [ ] 部署 backend stack: `sam deploy --guided --template infra/template.yaml --stack-name geo-backend`
- [ ] 部署 CF Function stack: `aws cloudformation deploy --template-file infra/cloudfront-function/template.yaml --stack-name geo-cf-function --parameter-overrides GeoApiDomain=<API_GW_DOMAIN>`
- [ ] 手動掛 CF Function 到現有 CloudFront distribution（viewer-request event）

## Phase 5: 測試

- [x] 基本功能測試 — `agentcore invoke --dev "what can you do"`
- [x] `evaluate_geo_score` 測試（TVBS 新聞 URL）
- [x] `generate_llms_txt` 測試
- [ ] `store_geo_content` 測試（需要 DDB 先部署）
- [ ] 端到端測試 — 模擬 AI bot User-Agent 請求，驗證 CF Function → API GW → Lambda → DDB 整條路徑
- [ ] `rewrite_content_for_geo` 測試

## Phase 6: PR & Review

- [ ] 推送所有 commit 到 GitHub
- [ ] 發 PR (`feature/edgecomputing` → `main`)
