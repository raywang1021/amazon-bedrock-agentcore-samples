# 架構說明

## Edge Serving 架構

```
AI Bot 訪問網站
      │
      ▼
┌──────────────────┐
│ CloudFront       │
│ (CDN)            │
└────────┬─────────┘
         │
┌────────▼─────────┐
│ CF Function      │
│ geo-bot-router   │
│ 偵測 User-Agent  │
│ 或 ?ua=genaibot  │
└───┬─────────┬────┘
    │         │
  AI Bot   一般使用者
    │         │
    ▼         ▼
┌────────┐  原本 Origin
│Lambda  │  (不變)
│Func URL│
└───┬────┘
    │
    ▼ 查 DDB
┌──────────────────────────────────┐
│ status=ready → 回傳 GEO 內容     │
│ status=processing → 回原始內容   │
│ 無資料 → 標記 processing         │
│          + 非同步觸發 generator  │
│          + 回原始內容            │
└──────────────────────────────────┘
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
- `handler_duration_ms`：handler Lambda 從收到 request 到回傳 response 的總時間（含 DDB 查詢、fetch original、invoke agent），只在 sync mode 寫入
- `generator_duration_ms`：generator Lambda 從啟動到完成的總時間（含 invoke agent + DDB 寫入），只在 async/passthrough mode 寫入

## Response Headers

Lambda 回傳的 response 會帶以下自訂 header：

| Header | 說明 | 出現時機 |
|--------|------|---------|
| `X-GEO-Optimized: true` | 標記為 GEO 優化內容 | cache hit / sync 產生成功 |
| `X-GEO-Source` | `cache`（DDB 快取）/ `generated`（sync 即時產生）/ `passthrough`（回原始內容） | 所有 response |
| `X-GEO-Handler-Ms` | handler Lambda 整體處理時間（ms） | 所有 response |
| `X-GEO-Duration-Ms` | AgentCore 產生時間（ms） | cache hit（來自 DDB）/ sync 產生 |
| `X-GEO-Created` | GEO 內容建立時間 | cache hit |

## CloudFront Function 偵測邏輯

`geo-bot-router` 透過兩種方式偵測 AI bot：

1. **User-Agent 比對**：GPTBot、ClaudeBot、PerplexityBot、BingBot 等常見 AI 爬蟲
2. **Querystring 模擬**：`?ua=genaibot` 用於測試

偵測到後，CFF 會：
- 加上 `x-geo-bot: true` 和 `x-geo-bot-ua` header
- 透過 `cf.updateRequestOrigin()` 將 request 導向 Lambda Function URL
