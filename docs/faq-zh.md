# FAQ

> [English](faq.md)

## 為什麼用 Agent，而不是直接寫 Python script 呼叫 Claude？

如果需求是固定的單一任務（例如批次評估一堆 URL 的 GEO 分數），直接寫 script 呼叫 Bedrock API 更快更簡單，只需要一次 Claude 呼叫。

用 Agent framework 的價值在於：

- **意圖判斷**：同一個入口可能要改寫內容、評估分數、或產生 llms.txt，由模型根據使用者的自然語言來決定呼叫哪個 tool
- **多步驟任務**：使用者可以說「先評估這個 URL，然後幫我改寫它的內容」，agent 能串接多個 tool 完成
- **對話式互動**：使用者可以追問、補充要求，agent 維持上下文

代價是多一次 Claude 呼叫來做意圖判斷。如果你的場景不需要這些彈性，直接用 script 是更好的選擇。

詳細的呼叫流程圖請參考 [架構說明](architecture-zh.md#agent-tool-呼叫流程)。

## Strands `@tool` vs MCP

這個專案的 tool 用 Strands 的 `@tool` decorator 定義，跟 agent 跑在同一個 process，呼叫就是 Python function call，沒有額外的網路開銷。

MCP (Model Context Protocol) 是標準化的 client/server 協議，tool 跑在獨立的 server 上，每次呼叫有 I/O 開銷，但好處是任何 MCP client 都能接。對這個專案來說，tool 不需要被其他 client 共用，用 `@tool` 更直接。

## 為什麼需要 sanitize？AgentCore / Guardrail 不夠嗎？

`sanitize_web_content()` 防的是 **indirect prompt injection** — 攻擊者在網頁內容裡埋惡意指令，透過 tool 餵進 LLM prompt。

攻擊路徑：

```
惡意網站（隱藏文字 "ignore all previous instructions..."）
  → fetch_page_text()
  → Agent tool 把內容塞進 prompt
  → LLM 被劫持，產出污染的 HTML
  → 存進 DDB → 透過 CloudFront CDN 大量散播
```

AgentCore 是 runtime/hosting 層，不會過濾 tool 傳進去的 prompt 內容。Bedrock Guardrail 的設計目標是 content safety（PII、仇恨言論等），不是防 prompt injection。

所以 sanitize 跟 Guardrail 是互補的：

| 防護層 | 防什麼 | 位置 |
|--------|--------|------|
| `sanitize.py` | Indirect prompt injection（來自網頁內容） | Tool 層，LLM 看到之前 |
| Bedrock Guardrail | Content safety（PII、仇恨、色情等） | LLM 層，input/output 過濾 |

sanitize 做三件事：
1. **Strip HTML comments** — 攻擊者常把指令藏在 `<!-- ... -->` 裡
2. **移除 invisible unicode** — zero-width characters 可繞過 regex 偵測
3. **Redact 已知 injection patterns** — `ignore all previous instructions`、`[INST]`、`<<SYS>>` 等 token

保護對象：直接保護 LLM 不被劫持，最終保護透過 CloudFront 拿到 GEO 內容的 AI 搜尋引擎和其用戶。任何把 untrusted external content 餵進 LLM 的系統都需要這層防護。
