# GEO Agent — 開發路線圖

> [English version](roadmap.md)

## 已完成

| 階段 | 說明 |
|------|------|
| Phase 1 | 專案基礎 — Strands Agent + AgentCore |
| Phase 2 | 安全性 — sanitize、guardrail、prompt injection 防護 |
| Phase 3 | Edge Computing — CloudFront OAC + Lambda Function URL |
| Phase 4 | 部署 — SAM template、多租戶 DDB |
| Phase 5 | 測試 — 60 個 unit tests、e2e 測試套件 |
| Phase 6 | PR & Review — [PR #1](https://github.com/KenexAtWork/geoagent/pull/1) |

### 重要里程碑
- Agent 無狀態 DDB 解耦（store_geo_content → geo-content-storage Lambda）
- CloudFront OAC 整合至主 template
- 多租戶 DDB key 格式：`{host}#{path}[?query]`
- Processing timeout（5 分鐘）+ 過期記錄自動恢復
- Purge + CF invalidation 聯動
- 共用 `fetch_page_text` + 統一 rewrite prompt
- 三視角 GEO 評分（as-is / original / geo），`temperature=0.1`
- Score tracking 使用 `update_scores` action（不覆寫完整記錄）
- 互動式 `setup.sh`，自動產生 `samconfig.toml`
- Timeout chain 對齊：client 80s < CF origin 85s < Lambda 90s

## 進行中

- [ ] 清理 OAC 測試 stack

## 待辦

### 效能
- [ ] Sync mode 效能優化（目前約 30s）

### 功能
- [ ] 透過 SSM Parameter Store 動態切換模型（免 redeploy 即可更換 MODEL_ID）
- [ ] 多語言 GEO 內容支援
- [ ] GEO 內容版本管理
- [ ] A/B 測試框架（比較不同改寫策略）
- [ ] CloudWatch Dashboard 分數趨勢視覺化

### 維運
- [ ] 成本分析與優化（如採樣評分）
- [ ] CI/CD 整合分數 regression 偵測
