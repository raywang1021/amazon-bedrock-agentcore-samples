# FAQ

## 為什麼用 Agent，而不是直接寫 Python script 呼叫 Claude？

如果需求是固定的單一任務（例如批次評估一堆 URL 的 GEO 分數），直接寫 script 呼叫 Bedrock API 更快更簡單，只需要一次 Claude 呼叫。

用 Agent framework 的價值在於：

- **意圖判斷**：同一個入口可能要改寫內容、評估分數、或產生 llms.txt，由模型根據使用者的自然語言來決定呼叫哪個 tool
- **多步驟任務**：使用者可以說「先評估這個 URL，然後幫我改寫它的內容」，agent 能串接多個 tool 完成
- **對話式互動**：使用者可以追問、補充要求，agent 維持上下文

代價是多一次 Claude 呼叫來做意圖判斷。如果你的場景不需要這些彈性，直接用 script 是更好的選擇。

詳細的呼叫流程圖請參考 [架構說明](architecture.md#agent-tool-呼叫流程)。

## Strands `@tool` vs MCP

這個專案的 tool 用 Strands 的 `@tool` decorator 定義，跟 agent 跑在同一個 process，呼叫就是 Python function call，沒有額外的網路開銷。

MCP (Model Context Protocol) 是標準化的 client/server 協議，tool 跑在獨立的 server 上，每次呼叫有 I/O 開銷，但好處是任何 MCP client 都能接。對這個專案來說，tool 不需要被其他 client 共用，用 `@tool` 更直接。
