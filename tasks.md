# GEO Agent — Task Tracker

## Phase 1: 專案基礎設定 ✅
## Phase 2: 安全性 ✅
## Phase 3: Edge Computing ✅

SAM template 支援 `OriginMode` 參數（`alb` / `oac`）

## Phase 4: 部署 ✅
## Phase 5: 測試 ✅

OAC 獨立測試通過（stack: `geo-oac-test`, CF: `dq324v08a4yas.cloudfront.net`）

## Phase 6: PR & Review

- [x] PR — https://github.com/KenexAtWork/geoagent/pull/1

## Backlog

### Done
- [x] Agent stateless DDB 解耦（store_geo_content → geo-content-storage Lambda → DDB）
- [x] CloudFront OAC — 已整合到主 template
- [x] DDB 加入 `host` 欄位（多租戶準備）
- [x] CF cache policy — 尊重 origin Cache-Control，whitelist ua/mode/purge

### Retro — 高優先
- [x] processing timeout — 卡住的 processing 記錄 5 分鐘後可重試
- [x] Purge + CF invalidation 聯動 — purge 時同時清 CF cache

### Retro — 中優先
- [x] 共用 `_fetch_page_text()` — 抽成 `src/tools/fetch.py`
- [x] 統一 rewrite prompt — 抽成 `src/tools/prompts.py`，`store_geo_content` 和 `rewrite_content_for_geo` 共用
- [x] CloudWatch Alarm — generator 失敗率、handler P99 延遲

### Retro — 低優先
- [x] 自動化測試（CI）— 59 unit tests + GitHub Actions workflow

### 功能
- [ ] 清理 OAC 測試 stack
- [ ] Sync mode 效能優化（目前 ~24s）
- [ ] 多語言 GEO 內容支援
- [ ] GEO 內容版本管理
