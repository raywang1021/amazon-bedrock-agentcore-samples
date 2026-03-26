# GEO Agent

> [English README](README.md)

Generative Engine Optimization (GEO) agent，透過 Bedrock AgentCore 部署，搭配 CloudFront OAC + Lambda Function URL 做 edge serving，讓 AI 搜尋引擎爬蟲拿到 GEO 優化過的內容。

## 功能

- **內容改寫**：自動偵測內容類型（新聞 / 電商 / 部落格 / FAQ / 通用），套用對應的 GEO 優化策略，輸出語義 HTML + JSON-LD schema markup + 結構化信號
- **GEO 評分**：五維度加權評分，對齊 AI 搜尋引擎排名信號 — authority (25%)、freshness (20%)、relevance (30%)、structure (15%)、readability (10%)，從三視角（as-is / original / geo）評估，使用 `temperature=0.1` 確保一致性
- **分數追蹤**：自動記錄改寫前後的 GEO 分數到 DynamoDB，追蹤優化成效（詳見 [分數追蹤文檔](docs/score-tracking.md)）
- **llms.txt 產生**：為網站產生 AI 友善的 llms.txt
- **Edge Serving**：CloudFront Function 偵測 AI bot，透過 OAC + Lambda Function URL 自動導向 GEO 優化內容
- **多租戶**：多個 CloudFront distribution 共用同一組 Lambda + DynamoDB，透過 `{host}#{path}` composite key 隔離
- **Guardrail（可選）**：透過 Bedrock Guardrail 過濾不當內容、防止 PII 洩漏

## 專案結構

```
src/
├── main.py                  # AgentCore 入口，Strands Agent 定義
├── model/load.py            # Model ID + Region + Guardrail 集中管理
└── tools/
    ├── fetch.py             # 共用網頁抓取（trafilatura + fallback，支援自訂 UA）
    ├── rewrite_content.py   # GEO 內容改寫
    ├── evaluate_geo_score.py # 三視角 GEO 評分（5 維度 × 3 視角）
    ├── generate_llms_txt.py # llms.txt 產生
    ├── store_geo_content.py # 抓網頁 → 改寫 → 評分（5 維度）→ 存 DynamoDB
    ├── prompts.py           # 分類型改寫 prompt（新聞/電商/部落格/FAQ/通用）
    └── sanitize.py          # Prompt injection 防護

infra/
├── template.yaml                    # SAM: DynamoDB + Lambda（OAC 架構）
├── cloudfront-distribution.yaml     # CloudFormation: 全新 CF distribution
├── lambda/
│   ├── geo_content_handler.py       # 服務 GEO 內容（3 種 cache-miss 模式）
│   ├── geo_generator.py             # 非同步呼叫 AgentCore 產生內容
│   ├── geo_storage.py               # Agent 寫入 DDB 的 storage service
│   └── cf_origin_setup.py           # Custom Resource: 自動設定既有 CF distribution
└── cloudfront-function/
    ├── geo-router-oac.js            # CFF: AI bot 偵測 + Lambda Function URL origin 切換
    └── template.yaml               # CFF CloudFormation template
```

## 快速開始

```bash
# 1. 設定 + 部署（一行搞定 — 安裝依賴、設定、部署 AgentCore + 基礎設施）
./setup.sh

# 2. 查詢分數追蹤資料
python scripts/query_scores.py --stats        # 顯示統計
python scripts/query_scores.py --top 10       # 前 10 名改善
python scripts/query_scores.py --url /path    # 查詢特定 URL
```

`setup.sh` 以互動方式處理所有步驟：建立 venv、產生 `samconfig.toml` + `.bedrock_agentcore.yaml`、執行 `agentcore deploy` 和 `sam deploy`。填完設定後會詢問「Deploy now?」— 回答 Y 即自動完成完整部署。
```

## 環境變數

| 變數 | 預設值 | 說明 |
|------|--------|------|
| `MODEL_ID` | `us.anthropic.claude-sonnet-4-20250514-v1:0` | Bedrock model ID |
| `AWS_REGION` | `us-east-1` | AWS region |
| `GEO_TABLE_NAME` | `geo-content` | DynamoDB table name |
| `BEDROCK_GUARDRAIL_ID` | （空） | Bedrock Guardrail ID（可選） |
| `BEDROCK_GUARDRAIL_VERSION` | `DRAFT` | Guardrail version |

## 文件

- [為什麼用 AgentCore](docs/why-agentcore.zh-TW.md) — AgentCore vs 直接呼叫 LLM、Tool Selection vs MCP、三層觸發架構
- [部署指南](docs/deployment.zh-TW.md) — AgentCore、SAM、CloudFront 部署步驟
- [架構說明](docs/architecture.zh-TW.md) — Edge Serving 架構、DDB Schema、Response Headers、HTML 驗證、多租戶
- [分數追蹤](docs/score-tracking.zh-TW.md) — GEO 改寫前後分數記錄與成效分析
- [FAQ](docs/faq.zh-TW.md) — 為什麼用 Agent、Tool 呼叫流程、@tool vs MCP
- [開發路線圖](docs/roadmap.zh-TW.md) — 開發進度與待辦事項

## Troubleshooting

### `RequestsDependencyWarning: urllib3 ... or chardet ...`

`prance`（`bedrock-agentcore-starter-toolkit` 的間接依賴）會拉入 `chardet`，跟 `requests` 偏好的 `charset_normalizer` 衝突。

```bash
pip uninstall chardet -y
```

`agentcore dev` 可能會重新安裝，再跑一次即可。
