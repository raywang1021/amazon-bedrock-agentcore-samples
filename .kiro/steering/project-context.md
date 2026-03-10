---
inclusion: auto
---

# GEO Agent 專案概覽

這是一個 Generative Engine Optimization (GEO) Agent，部署在 Amazon Bedrock AgentCore 上。

## 技術棧
- Framework: Strands Agents
- Model: Claude Sonnet 4 via Amazon Bedrock
- Runtime: BedrockAgentCoreApp (ASGI)
- 語言: Python 3.10+

## 架構重點
- 模型設定統一在 `src/model/load.py`，所有 tool 都從這裡 import，不要 hardcode model ID
- MODEL_ID、AWS_REGION、BEDROCK_GUARDRAIL_ID 都透過環境變數控制
- 每個 tool 內部建立獨立的 sub-agent 處理子任務（agent-in-agent 模式）
- 網頁內容抓取後必須經過 `src/tools/sanitize.py` 過濾，防止 indirect prompt injection

## 三個核心 Tool
1. `rewrite_content_for_geo` — 改寫文字內容為 GEO 優化版本
2. `evaluate_geo_score` — 評估 URL 的 GEO 分數（引用來源、統計數據、權威性）
3. `generate_llms_txt` — 為網站產生 llms.txt 檔案
