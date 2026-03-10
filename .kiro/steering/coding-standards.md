---
inclusion: auto
---

# Coding Standards

## Python
- 使用 type hints
- Docstring 使用 Google style（Args / Returns）
- Import 順序：stdlib → third-party → local

## 安全性
- 任何從外部抓取的內容（網頁、API 回應）在送進模型前必須經過 `sanitize_web_content()` 過濾
- 不要在程式碼中 hardcode AWS credentials 或 secrets
- 敏感設定一律用環境變數

## 模型呼叫
- 所有 BedrockModel 實例必須透過 `src/model/load.py` 的 `load_model()` 建立
- 不要在 tool 裡直接 import BedrockModel 並自行初始化
- Sub-agent 的 system prompt 必須包含防 prompt injection 的指令

## 新增 Tool
- 放在 `src/tools/` 目錄下
- 使用 `@tool` decorator（from strands）
- 在 `src/main.py` 的 Agent tools list 中註冊
- 在 SYSTEM_PROMPT 中加入 tool 說明和選擇邏輯
