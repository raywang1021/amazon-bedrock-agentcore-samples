# 架構說明

## 系統總覽

```
使用者/管理員                        AI Bot (GPTBot, ClaudeBot...)
     │                                      │
     │ agentcore invoke                     │ 訪問網站
     ▼                                      ▼
┌──────────────┐                   ┌──────────────────┐
│ AgentCore    │                   │ CloudFront       │
│ GEO Agent    │                   │ (CDN)            │
│              │                   └────────┬─────────┘
│ 4 Tools:     │                            │
│ - rewrite    │                   ┌────────▼─────────┐
│ - evaluate   │                   │ CF Function      │
│ - llms.txt   │                   │ geo-bot-router   │
│ - store_geo  │                   │ 偵測 User-Agent  │
└──────┬───────┘                   │ 或 ?ua=genaibot  │
       │                           └───┬─────────┬────┘
       │ 寫入                          │         │
       ▼                          AI Bot│    一般使用者
┌──────────────┐                       ▼         ▼
│ DynamoDB     │              ┌────────────┐  原本 Origin
│ geo-content  │◄─────────────│ Lambda     │  (不變)
└──────────────┘   Lambda 讀取 │ Function   │
                              │ URL        │
                              └────────────┘
```

## Agent Tool 呼叫流程

以 `evaluate_geo_score` 為例，一次完整的呼叫會經過兩次 Bedrock API call（Main agent 意圖判斷 + Sub-agent 執行），這是延遲的主要來源。

```mermaid
sequenceDiagram
    participant User
    participant AgentCore
    participant MainAgent as Strands Agent
    participant Claude1 as Claude (Main)
    participant Tool as evaluate_geo_score
    participant Sanitize as sanitize
    participant Claude2 as Claude (Sub-agent)

    User->>AgentCore: "評估 GEO 分數: https://..."
    AgentCore->>MainAgent: payload + prompt
    MainAgent->>Claude1: prompt + tools list
    Claude1-->>MainAgent: tool_use: evaluate_geo_score(url)
    MainAgent->>Tool: call function(url)
    Tool->>Tool: fetch webpage (requests + trafilatura)
    Tool->>Sanitize: sanitize_web_content(raw text)
    Sanitize-->>Tool: cleaned text
    Tool->>Claude2: EVAL_SYSTEM_PROMPT + cleaned text
    Claude2-->>Tool: JSON scores
    Tool-->>MainAgent: tool result (JSON)
    MainAgent->>Claude1: tool result
    Claude1-->>MainAgent: final response
    MainAgent-->>AgentCore: stream response
    AgentCore-->>User: streaming text
```

```
User          AgentCore      Strands Agent   Claude (Main)   evaluate_geo_score  sanitize    Claude (Sub)
 │                │                │               │                │               │              │
 │  prompt        │                │               │                │               │              │
 │───────────────>│  payload       │               │                │               │              │
 │                │───────────────>│  prompt+tools  │                │               │              │
 │                │                │──────────────>│                │               │              │
 │                │                │  tool_use     │                │               │              │
 │                │                │<──────────────│                │               │              │
 │                │                │  call(url)    │                │               │              │
 │                │                │──────────────────────────────>│               │              │
 │                │                │               │                │  fetch webpage │              │
 │                │                │               │                │──> requests   │              │
 │                │                │               │                │<── html       │              │
 │                │                │               │                │  sanitize()   │              │
 │                │                │               │                │──────────────>│              │
 │                │                │               │                │  clean text   │              │
 │                │                │               │                │<──────────────│              │
 │                │                │               │                │  prompt+text  │              │
 │                │                │               │                │─────────────────────────────>│
 │                │                │               │                │  JSON scores  │              │
 │                │                │               │                │<─────────────────────────────│
 │                │                │  tool result  │                │               │              │
 │                │                │<──────────────────────────────│               │              │
 │                │                │  tool result  │                │               │              │
 │                │                │──────────────>│                │               │              │
 │                │                │  response     │                │               │              │
 │                │                │<──────────────│                │               │              │
 │                │  stream        │               │                │               │              │
 │                │<───────────────│               │                │               │              │
 │  streaming text│                │               │                │               │              │
 │<───────────────│                │               │                │               │              │
```

## Edge Serving 流程

AI bot 訪問網站時，CloudFront Function 偵測 User-Agent 並切換 origin 到 Lambda Function URL。

### Passthrough 模式（預設）

```mermaid
sequenceDiagram
    participant Bot as AI Bot
    participant CF as CloudFront
    participant CFF as CF Function
    participant Lambda as geo-content-handler
    participant DDB as DynamoDB
    participant Gen as geo-content-generator
    participant AC as AgentCore

    Bot->>CF: GET /world/3149600
    CF->>CFF: viewer-request
    CFF->>CFF: 偵測 AI bot User-Agent
    CFF->>Lambda: 切換 origin + x-origin-verify header
    Lambda->>DDB: get_item(url_path)

    alt status=ready (cache hit)
        DDB-->>Lambda: GEO 內容
        Lambda-->>Bot: 200 + GEO HTML
    else 無資料 (cache miss)
        DDB-->>Lambda: (empty)
        Lambda->>DDB: put_item(status=processing)
        Lambda->>Gen: invoke(async)
        Lambda->>Lambda: fetch 原始網頁
        Lambda-->>Bot: 200 + 原始 HTML
        Gen->>AC: invoke_agent_runtime
        AC-->>Gen: GEO 內容
        Gen->>DDB: put_item(status=ready)
    end
```

### Sync 模式

```mermaid
sequenceDiagram
    participant Bot as AI Bot
    participant Lambda as geo-content-handler
    participant DDB as DynamoDB
    participant AC as AgentCore

    Bot->>Lambda: GET /path?mode=sync
    Lambda->>DDB: get_item → cache miss
    Lambda->>DDB: put_item(status=processing)
    Lambda->>AC: invoke_agent_runtime（等待 ~30-40s）
    AC-->>Lambda: 完成
    Lambda->>DDB: get_item → status=ready
    Lambda->>DDB: update(handler_duration_ms, generation_duration_ms)
    Lambda-->>Bot: 200 + GEO HTML
```

## Cache Miss 模式

Lambda 支援三種 cache miss 處理模式，透過 querystring `?mode=` 切換：

| 模式 | querystring | 行為 | 適用場景 |
|------|------------|------|---------|
| passthrough（預設）| 無 或 `?mode=passthrough` | 回原始內容 + 非同步產生 | 正式環境，bot 不會空手而歸 |
| async | `?mode=async` | 回 202 + 非同步產生 | 測試用 |
| sync | `?mode=sync` | 等 AgentCore 產生完才回 | 測試用，需較長 timeout |

## DynamoDB Schema

Table: `geo-content`，partition key: `url_path` (S)

| 欄位 | 類型 | 說明 |
|------|------|------|
| `url_path` | S | URL 路徑（partition key） |
| `status` | S | `processing`（產生中）/ `ready`（可服務） |
| `geo_content` | S | GEO 優化後的 HTML 內容 |
| `content_type` | S | Content-Type，通常 `text/html; charset=utf-8` |
| `original_url` | S | 原始完整 URL |
| `mode` | S | 觸發模式：`sync` / `async` |
| `created_at` | S | 記錄建立時間（ISO 8601 UTC） |
| `updated_at` | S | 最後更新時間 |
| `generation_duration_ms` | N | AgentCore 產生 GEO 內容的純時間（ms） |
| `handler_duration_ms` | N | handler Lambda 整體處理時間（sync mode 寫入） |
| `generator_duration_ms` | N | generator Lambda 整體處理時間（async/passthrough mode 寫入） |
| `ttl` | N | DynamoDB TTL（Unix timestamp，可選） |

### 時間欄位說明

- `generation_duration_ms`：純粹 AgentCore invoke 的時間，不含 DDB 讀寫
- `handler_duration_ms`：handler Lambda 從收到 request 到回傳 response 的總時間，只在 sync mode 寫入
- `generator_duration_ms`：generator Lambda 從啟動到完成的總時間，只在 async/passthrough mode 寫入

## Response Headers

Lambda 回傳的 response 會帶以下自訂 header：

| Header | 說明 | 出現時機 |
|--------|------|---------|
| `X-GEO-Optimized: true` | 標記為 GEO 優化內容 | cache hit / sync 產生成功 |
| `X-GEO-Source` | `cache` / `generated` / `passthrough` | 所有 response |
| `X-GEO-Handler-Ms` | handler Lambda 整體處理時間（ms） | 所有 response |
| `X-GEO-Duration-Ms` | AgentCore 產生時間（ms） | cache hit / sync 產生 |
| `X-GEO-Created` | GEO 內容建立時間 | cache hit |

## Origin 保護

目前使用 custom header 驗證：CFF 加上 `x-origin-verify` header，Lambda 檢查是否匹配。不匹配回 403。

後續計畫改用 CloudFront OAC（Origin Access Control），Lambda Function URL 設 `AuthType: AWS_IAM`，由 CloudFront 用 SigV4 簽署 request。

## CloudFront Function 偵測邏輯

`geo-bot-router` 透過兩種方式偵測 AI bot：

1. User-Agent 比對：GPTBot、ClaudeBot、PerplexityBot、BingBot 等常見 AI 爬蟲
2. Querystring 模擬：`?ua=genaibot` 用於測試

偵測到後，CFF 會：
- 加上 `x-geo-bot: true`、`x-geo-bot-ua`、`x-origin-verify` header
- 透過 `cf.updateRequestOrigin()` 將 request 導向 Lambda Function URL
