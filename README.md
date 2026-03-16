# GEO Agent

Generative Engine Optimization (GEO) agent，透過 Bedrock AgentCore 部署，搭配 CloudFront + Lambda 做 edge serving，讓 AI 搜尋引擎爬蟲拿到 GEO 優化過的內容。

## 功能

- **內容改寫**：將網頁內容改寫為 GEO 最佳化格式（結構化標題、Q&A、E-E-A-T 信號）
- **GEO 評分**：三視角（as-is / original / geo）分析 URL 的 GEO 準備度，各給出三維度評分（cited_sources / statistical_addition / authoritative），使用 `temperature=0.1` 確保一致性
- **llms.txt 產生**：為網站產生 AI 友善的 llms.txt
- **Edge Serving**：CloudFront Function 偵測 AI bot，自動導向 GEO 優化內容

## 專案結構

```
src/
├── main.py                  # AgentCore 入口，Strands Agent 定義
├── model/load.py            # Model ID + Region 集中管理
└── tools/
    ├── fetch.py             # 共用網頁抓取（trafilatura + fallback，支援自訂 UA）
    ├── rewrite_content.py   # GEO 內容改寫
    ├── evaluate_geo_score.py # 三視角 GEO 評分（as-is / original / geo）
    ├── generate_llms_txt.py # llms.txt 產生
    ├── store_geo_content.py # 抓網頁 → 改寫 → 存 DynamoDB
    ├── prompts.py           # 共用 rewrite prompt
    └── sanitize.py          # Prompt injection 防護

infra/
├── template.yaml                    # SAM: DynamoDB + Lambda（支援 ALB / OAC 雙模式）
├── lambda/
│   ├── geo_content_handler.py       # 服務 GEO 內容（3 種 cache-miss 模式）
│   ├── geo_generator.py             # 非同步呼叫 AgentCore 產生內容
│   └── geo_storage.py               # Agent 寫入 DDB 的 storage service
└── cloudfront-function/
    ├── geo-router.js                # CFF: AI bot 偵測 + ALB origin 切換
    ├── geo-router-oac.js            # CFF: AI bot 偵測 + Lambda Function URL origin 切換（OAC）
    └── template.yaml               # CFF CloudFormation template
```

## 快速開始

```bash
# 1. 環境設定
./setup.sh
source .venv/bin/activate

# 2. AWS 設定
agentcore configure

# 3. 本地開發
agentcore dev
agentcore invoke --dev "What can you do"

# 4. 部署
agentcore deploy
```

## 環境變數

| 變數 | 預設值 | 說明 |
|------|--------|------|
| `MODEL_ID` | `us.anthropic.claude-sonnet-4-20250514` | Bedrock model ID |
| `AWS_REGION` | `us-east-1` | AWS region |
| `GEO_TABLE_NAME` | `geo-content` | DynamoDB table name |
| `BEDROCK_GUARDRAIL_ID` | （空） | Bedrock Guardrail ID（可選） |
| `BEDROCK_GUARDRAIL_VERSION` | `DRAFT` | Guardrail version |

## 文件

- [為什麼用 AgentCore](docs/why-agentcore.md) — AgentCore vs 直接呼叫 LLM、Tool Selection vs MCP、三層觸發架構
- [部署指南](docs/deployment.md) — AgentCore、SAM、CloudFront 部署步驟
- [架構說明](docs/architecture.md) — Edge Serving 架構、DDB Schema、Response Headers
- [FAQ](docs/faq.md) — 為什麼用 Agent、Tool 呼叫流程、@tool vs MCP

## Troubleshooting

### `RequestsDependencyWarning: urllib3 ... or chardet ...`

`prance`（`bedrock-agentcore-starter-toolkit` 的間接依賴）會拉入 `chardet`，跟 `requests` 偏好的 `charset_normalizer` 衝突。

```bash
pip uninstall chardet -y
```

`agentcore dev` 可能會重新安裝，再跑一次即可。
