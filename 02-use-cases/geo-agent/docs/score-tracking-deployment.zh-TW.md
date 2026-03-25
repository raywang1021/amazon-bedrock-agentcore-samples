# GEO 分數追蹤 - 部署指南

> [English](score-tracking-deployment.md)

## 部署前檢查

在部署更新之前，請確認以下事項：

### 1. 代碼變更確認

已修改的檔案：
- ✅ `src/tools/store_geo_content.py` - 新增分數評估功能
- ✅ `infra/lambda/geo_storage.py` - 支援儲存分數欄位
- ✅ `infra/lambda/geo_generator.py` - 複製分數欄位
- ✅ `infra/template.yaml` - 添加 schema 註釋

### 2. 測試驗證

```bash
# 運行分數追蹤測試
cd test
python test_score_tracking.py
```

預期輸出：
```
✓ Item stored successfully!
  Original score: 45
  GEO score: 78
  Improvement: +33
✓ All score fields verified!
✓ Test completed successfully!
```

## 部署步驟

```bash
# 1. 確保在虛擬環境中
source .venv/bin/activate

# 2. 部署 Agent（包含新的評分功能）
agentcore deploy

# 3. 部署 SAM 基礎設施（Lambda 函數）
sam build -t infra/template.yaml
sam deploy -t infra/template.yaml
```

## 部署後驗證

### 1. 測試完整流程

```bash
# 使用 AgentCore 測試
agentcore invoke "請為 https://example.com/test-article 生成並儲存 GEO 優化內容"
```

### 2. 檢查 DynamoDB 資料

```bash
# 查詢最近儲存的項目
aws dynamodb scan \
  --table-name geo-content \
  --limit 1 \
  --region us-east-1 \
  --projection-expression "url_path, original_score, geo_score, score_improvement"
```

預期看到類似輸出：
```json
{
  "Items": [
    {
      "url_path": {"S": "/test-article"},
      "original_score": {
        "M": {
          "overall_score": {"N": "45"}
        }
      },
      "geo_score": {
        "M": {
          "overall_score": {"N": "78"}
        }
      },
      "score_improvement": {"N": "33"}
    }
  ]
}
```

### 3. 檢查 Lambda 日誌

```bash
# 查看 Storage Lambda 日誌
aws logs tail /aws/lambda/geo-content-storage --follow

# 查看 Generator Lambda 日誌
aws logs tail /aws/lambda/geo-content-generator --follow
```

## 向後兼容性

此更新完全向後兼容：

- ✅ 現有的 DynamoDB 項目不受影響
- ✅ 分數欄位是可選的（optional）
- ✅ 沒有分數的舊項目仍可正常讀取和服務
- ✅ 新項目會自動包含分數資訊

## 成本影響

新增分數追蹤功能會增加以下成本：

1. **Bedrock API 調用**
   - 每次儲存內容會額外進行 2 次 LLM 調用（改寫前後各一次評分）
   - 每次評分約使用 8000 tokens
   - 預估成本：每次儲存增加約 $0.01-0.02（取決於模型）

2. **DynamoDB 儲存**
   - 每個項目增加約 1-2 KB（分數 JSON 資料）
   - 影響微乎其微（PAY_PER_REQUEST 模式）

3. **Lambda 執行時間**
   - 每次儲存增加約 3-5 秒（評分時間）
   - 預估成本增加：每次約 $0.0001

## 優化建議

如果成本是考量因素，可以考慮：

### 選項 1: 條件式評分

修改 `store_geo_content.py`，只在特定條件下評分：

```python
# 只對重要頁面評分
if should_track_score(url):
    original_score = _evaluate_content_score(clean_text, "original")
    geo_score = _evaluate_content_score(geo_content, "geo-optimized")
else:
    original_score = None
    geo_score = None
```

### 選項 2: 採樣評分

只對一定比例的請求進行評分：

```python
import random

# 10% 採樣率
if random.random() < 0.1:
    original_score = _evaluate_content_score(clean_text, "original")
    geo_score = _evaluate_content_score(geo_content, "geo-optimized")
```

### 選項 3: 批次評分

使用獨立的批次處理流程，定期對已儲存的內容進行評分。

## 回滾計劃

如果需要回滾到沒有分數追蹤的版本：

```bash
# 1. 回滾 Git 提交
git revert HEAD

# 2. 重新部署
agentcore deploy
sam build && sam deploy
```

現有的分數資料會保留在 DynamoDB 中，不會影響系統運作。

## 監控建議

建議設置以下 CloudWatch 告警：

1. **評分失敗率**
   - 監控 Lambda 錯誤日誌中的評分失敗
   
2. **執行時間增加**
   - 監控 `store_geo_content` 工具的執行時間
   - 設置閾值：> 30 秒觸發告警

3. **成本異常**
   - 監控 Bedrock API 調用次數
   - 設置每日預算告警

## 疑難排解

### 問題 1: 評分失敗但內容正常儲存

**症狀**: DynamoDB 中有內容但沒有分數欄位

**原因**: 評分 LLM 調用失敗，但不影響內容儲存

**解決**: 檢查 Lambda 日誌，確認 Bedrock 權限和配額

### 問題 2: 部署後分數欄位為空

**症狀**: 新儲存的項目沒有分數

**原因**: Agent 代碼未更新或環境變數問題

**解決**: 
```bash
# 確認 Agent 已重新部署
agentcore deploy --force

# 檢查 Lambda 環境變數
aws lambda get-function-configuration \
  --function-name geo-content-storage
```

### 問題 3: 評分時間過長

**症狀**: 儲存操作超時

**解決**: 
- 增加 Lambda timeout（在 template.yaml 中）
- 減少評分內容長度（調整 MAX_CHARS）
- 考慮使用更快的模型

## 支援

如有問題，請查看：
- [分數追蹤功能文檔](score-tracking.zh-TW.md)
- [架構說明](architecture.zh-TW.md)
- [FAQ](faq.zh-TW.md)
