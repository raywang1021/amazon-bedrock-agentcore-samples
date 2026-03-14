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

- [x] Agent stateless DDB 解耦（store_geo_content → geo-content-storage Lambda → DDB）
- [x] CloudFront OAC — 已整合到主 template
- [ ] 清理 OAC 測試 stack
- [ ] Sync mode 效能優化（目前 ~24s）
- [ ] 多語言 GEO 內容支援
- [ ] GEO 內容版本管理
