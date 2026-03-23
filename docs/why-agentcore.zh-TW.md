# 為什麼用 AgentCore？

> [English](why-agentcore.md)

## AgentCore 是什麼

AgentCore 解決的核心問題是：把 AI agent 從 prototype 搬到 production 的基礎設施缺口。

直接呼叫 Bedrock Converse API，你得到的是「一次 LLM 推理」。但 agent 不只是一次推理 — agent 需要推理、決定用哪個 tool、執行 tool、再推理、再決定... 這個 loop 需要一整套 infra 來支撐。

AgentCore 提供的就是這套 infra：

| 模組 | 解決什麼問題 |
|------|-------------|
| Runtime | Serverless 部署 + session 隔離 + auto-scaling |
| Memory | Session 短期記憶 + 跨 session 長期記憶（語意搜尋） |
| Identity | Agent 代表使用者存取第三方服務（OAuth、API key vault） |
| Gateway | 把現有 API/Lambda 包裝成 MCP tool，統一介面 + 認證 + 限流 |
| Observability | Agent 執行的 trace、span、token 用量、延遲，內建 dashboard |
| Code Interpreter | 隔離環境跑 agent 產生的程式碼 |
| Browser | 託管瀏覽器讓 agent 操作網頁 |

簡單說：Converse API 是「一次 LLM 呼叫」，AgentCore 是「把整個 agent 當成一個 managed service 來跑」。

## Tool Selection vs MCP

Tool selection 是 LLM 的能力 — 你給它一組 tool 的描述，LLM 根據 prompt 決定要呼叫哪個。這是 Claude、Nova 等模型本身支援的 function calling 功能。

MCP（Model Context Protocol）是標準化的介面協定 — 定義 tool 怎麼被發現、怎麼被呼叫、參數格式。它解決的是「tool 的連接方式」，不是「選哪個 tool」。

它們的關係：

```
MCP 定義介面格式
    ↓
AgentCore Gateway 把現有 API/Lambda 包裝成 MCP tool
    ↓
Agent framework (Strands) 把 tool 描述送給 LLM
    ↓
LLM 做 tool selection（決定用哪個）
    ↓
Framework 執行被選中的 tool
```

本專案的 4 個 tools 是用 `@tool` decorator 直接定義在 Python 裡，沒有走 MCP。但如果未來要接外部系統（CMS API、SEO 平台），可以透過 AgentCore Gateway 包成 MCP tool。

## 本專案中 AgentCore 的價值

GEO Agent 有 4 個 tools，使用者可以用自然語言跟它互動，agent 自己判斷要用哪個 tool、用幾次、怎麼串接。

例如一句（以下為虛構範例，不指涉任何實際業者）：

> 「評估這幾個新聞網站的 GEO 分數，低於 60 的幫我改寫並部署」

Agent 會自動拆解成：

```
1. 對每個網站呼叫 evaluate_geo_score
   → 媒體 A: 72 ✓  媒體 B: 45 ✗  媒體 C: 38 ✗
2. 對低於 60 的呼叫 store_geo_content（改寫 + 存入 DDB）
3. 回報結果
```

更多組合範例：

| 使用者說 | Agent 自動組合的 tools |
|---------|----------------------|
| 「幫我把這篇文章 GEO 優化後部署上去」 | rewrite → store_geo |
| 「評估這個網站，低於 60 就改寫並部署」 | evaluate → store_geo |
| 「幫這個網站產生 llms.txt」 | generate_llms_txt |
| 「比較這兩個 URL 的 GEO 分數」 | evaluate × 2 → 比較 |

這種「一句話觸發多步驟、多 tool 組合」的能力，是單純呼叫 LLM API 做不到的。

## Multi-Tenant 共用架構：加一個 Origin 不用改 Agent

這個專案的架構天然支援多租戶（multi-tenant）。當你要為一個新網站啟用 GEO 服務時，只需要建一個新的 CloudFront distribution 指向該網站，agent 和 Lambda 完全不用動。

```
                    ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
                    │  CF Dist A   │  │  CF Dist B   │  │  CF Dist C   │
                    │ news.xxx.com │  │ 24h.shop.com │  │ blog.yyy.com │
                    └──────┬───────┘  └──────┬───────┘  └──────┬───────┘
                           │                 │                 │
                           │    CFF: AI bot? │                 │
                           └────────┬────────┘─────────────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │  Lambda (共用)       │
                         │  geo-content-handler │
                         └──────────┬──────────┘
                                    │ cache miss
                                    ▼
                         ┌─────────────────────┐
                         │  AgentCore Agent     │
                         │  (共用，自動判斷      │
                         │   內容類型 + 改寫)    │
                         └─────────────────────┘
```

分工：

| 層級 | 職責 | 是否共用 |
|------|------|---------|
| CloudFront + CFF | 路由：一般使用者 → origin，AI bot → Lambda | 每個 origin 各一份 |
| Lambda | Serving：從 DynamoDB 拿 GEO 內容回傳 | 共用 |
| AgentCore Agent | 智慧層：抓取內容 → 判斷類型（電商/新聞/FAQ/部落格）→ 選對應策略改寫 | 共用 |
| DynamoDB | 儲存 | 共用 |

關鍵在於 `prompts.py` 裡的內容類型判斷。Agent 會根據抓到的內容自動分類（ECOMMERCE、NEWS、FAQ、BLOG_TUTORIAL、GENERAL），然後套用對應的改寫策略。這代表：

- 新增一個 origin 只需要一個 `aws cloudformation create-stack`
- 不需要為不同類型的網站寫不同的處理邏輯
- 內容策略的迭代（調 prompt、加新類型）只要 `agentcore deploy`，不影響 serving infra

這就是 AgentCore 在這個專案帶來的核心好處：把「判斷 + 改寫」的複雜邏輯從 infra 層抽離，交給 agent 處理。Infra 負責 routing 和 serving，agent 負責思考和產出，兩邊各司其職，scale 時互不干擾。

### 如果不用這個架構呢？

沒有 AgentCore 的話，內容類型判斷和改寫邏輯就得寫在 Lambda 裡面。常見做法：

1. **Lambda 裡寫 rule-based 判斷** — 用 URL pattern、HTML meta tag、或 DOM 結構去猜內容類型，再 mapping 到不同的 prompt template。這邏輯會越寫越複雜，每加一種網站可能就要調規則。

2. **每個 origin 寫死對應的 prompt** — 比如 PChome 就固定用電商 prompt，台灣大哥大就固定用 FAQ prompt。簡單但完全沒彈性，同一個網站裡如果有不同類型的頁面（比如電商網站裡的 FAQ 頁）就會改寫錯。

3. **Lambda 裡先呼叫一次 LLM 做分類，再呼叫一次做改寫** — 等於你自己在 Lambda 裡手刻了 agent 的 tool selection loop，但沒有 session、沒有 memory、沒有 observability，而且 Lambda timeout 會是個問題。

現在的架構，這些全部交給 agent 一句 prompt 搞定。LLM 本身就擅長理解內容語意，讓它自己判斷類型比你寫 regex 或 rule 準確得多，而且新類型只要在 `prompts.py` 加一段策略就好，不用動任何 infra。

## 實際落地：三層觸發架構

實際部署時，GEO 內容的產生會有三條路徑並存：

```
                    ┌─────────────────────────────────┐
                    │         GEO 內容產生              │
                    └──────┬──────────┬───────────┬────┘
                           │          │           │
                    ┌──────▼───┐ ┌────▼─────┐ ┌───▼──────────┐
                    │ CMS 發布  │ │ 管理員   │ │ Bot 首次來訪  │
                    │ webhook  │ │ 自然語言  │ │ (兜底)       │
                    └──────┬───┘ └────┬─────┘ └───┬──────────┘
                           │          │           │
                    直接呼叫    AgentCore    Handler async
                    Bedrock API  Agent      generation
                           │          │           │
                           └──────────┴───────────┘
                                      │
                                      ▼
                               DDB (status=ready)
                                      │
                                      ▼
                           Bot 來訪 → cache hit
```

| 觸發方式 | 走什麼 | 適合場景 |
|---------|--------|---------|
| CMS 發布 webhook | Lambda 直接呼叫 Bedrock API | 自動化、固定流程、低延遲 |
| 管理員自然語言 | AgentCore agent | 臨時需求、批次評估、探索性操作 |
| Bot 首次來訪 | Handler async generation | 兜底，沒被預先處理的頁面 |

### CMS Webhook 路徑

```
編輯按下「發布」
    │
    ├─ CMS 正常發布流程
    │
    └─ webhook → Lambda → fetch → Bedrock rewrite → DDB (ready)
                                    （背景 12-20s，無人等待）
```

這條路徑不需要 agent 做 tool selection — 動作是固定的（fetch → rewrite → store），直接呼叫 Bedrock Converse API 更快也更便宜。

而且文章剛發布的前幾分鐘通常是 bot 最可能來抓的時候（RSS feed 更新、sitemap 變動），如果這時候 GEO 內容已經 ready，命中率最高。

### 總結

- AgentCore 的價值在互動式場景：自然語言 → 多 tool 組合 → 條件判斷 → 自動執行
- 固定流程（CMS webhook）直接呼叫 Bedrock API 更高效
- 三層並存確保 bot 不管什麼時候來都有內容可拿
