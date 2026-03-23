# GEO 分數追蹤功能

> [English](score-tracking.md)

## 概述

此功能會在 GEO 內容改寫前後自動評估並儲存分數到 DynamoDB，以便追蹤 GEO 優化的成效。

## 功能特點

### 1. 自動評分
當使用 `store_geo_content` 工具時，系統會：
- 在改寫前評估原始內容的 GEO 分數
- 在改寫後評估優化內容的 GEO 分數
- 計算分數提升幅度

### 2. 評分維度
每次評分包含三個維度（0-100 分）：
- **cited_sources**: 內容是否有引用來源、研究或參考資料
- **statistical_addition**: 是否包含具體數據、百分比、統計資料
- **authoritative**: 是否有明確的作者署名和權威性信號（E-E-A-T）

### 3. DynamoDB 儲存結構

儲存在 DynamoDB 的項目包含以下欄位：

```json
{
  "url_path": "/world/3149600",
  "geo_content": "<html>...</html>",
  "original_score": {
    "overall_score": 45,
    "dimensions": {
      "cited_sources": {"score": 40},
      "statistical_addition": {"score": 35},
      "authoritative": {"score": 60}
    }
  },
  "geo_score": {
    "overall_score": 78,
    "dimensions": {
      "cited_sources": {"score": 80},
      "statistical_addition": {"score": 75},
      "authoritative": {"score": 80}
    }
  },
  "score_improvement": 33,
  "generation_duration_ms": 5432,
  "created_at": "2026-03-16T10:30:00Z",
  "updated_at": "2026-03-16T10:30:00Z"
}
```

## 使用方式

### 透過 Agent 使用

```python
# Agent 會自動調用 store_geo_content 工具
prompt = "請為 https://example.com/article/123 生成並儲存 GEO 優化內容"
```

Agent 會返回包含分數改善資訊的結果：
```
GEO content stored for /article/123
Content: 8543 chars, generated in 5432ms
Score improvement: 45 → 78 (+33.0)
```

### 直接調用工具

```python
from tools.store_geo_content import store_geo_content

result = store_geo_content("https://example.com/article/123")
print(result)
```

## 查詢分數資料

### 使用 AWS CLI

```bash
aws dynamodb get-item \
  --table-name geo-content \
  --key '{"url_path": {"S": "/article/123"}}' \
  --region us-east-1
```

### 使用 Python boto3

```python
import boto3

dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
table = dynamodb.Table("geo-content")

response = table.get_item(Key={"url_path": "/article/123"})
item = response.get("Item")

if item:
    print(f"Original score: {item['original_score']['overall_score']}")
    print(f"GEO score: {item['geo_score']['overall_score']}")
    print(f"Improvement: +{item['score_improvement']}")
```

## 測試

執行測試腳本驗證功能：

```bash
cd test
python test_score_tracking.py
```

## 成效分析

### 查詢平均改善幅度

可以使用 DynamoDB Scan 操作來分析所有項目的平均分數改善：

```python
import boto3
from decimal import Decimal

dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
table = dynamodb.Table("geo-content")

response = table.scan(
    ProjectionExpression="score_improvement, original_score, geo_score"
)

improvements = [
    float(item.get("score_improvement", 0))
    for item in response["Items"]
    if "score_improvement" in item
]

if improvements:
    avg_improvement = sum(improvements) / len(improvements)
    print(f"Average score improvement: +{avg_improvement:.1f}")
    print(f"Total items analyzed: {len(improvements)}")
```

### 找出改善最大的內容

```python
response = table.scan()
items = response["Items"]

# 按改善幅度排序
sorted_items = sorted(
    items,
    key=lambda x: float(x.get("score_improvement", 0)),
    reverse=True
)

print("Top 10 improvements:")
for item in sorted_items[:10]:
    print(f"{item['url_path']}: +{item.get('score_improvement', 0)}")
```

## 注意事項

1. **評分成本**: 每次儲存內容會進行兩次 LLM 評分調用（改寫前後各一次），會增加處理時間和成本
2. **評分一致性**: 使用 temperature=0.1 來確保評分的一致性和可重現性
3. **內容截斷**: 評分時會將內容截斷至 8000 字元以控制成本
4. **DynamoDB 容量**: 分數資料會增加每個項目的大小，請確保有足夠的儲存容量

## 分數儀表板

每個 CloudFront distribution 都內建了分數儀表板，透過 `?action=scores` 參數存取。

### 存取方式

```
https://<cf-domain>/?ua=genaibot&action=scores
```

範例：
- SETN: `https://dlmwhof468s34.cloudfront.net/?ua=genaibot&action=scores`
- TVBS: `https://dq324v08a4yas.cloudfront.net/?ua=genaibot&action=scores`

### 功能

- 多租戶隔離：每個 domain 只能看到自己的 DDB 資料（以 `begins_with(url_path, "{host}#")` 過濾）
- 可排序欄位：路徑、狀態、原始分數、GEO 分數、改善幅度（+/-）、生成時間（ms）、建立時間
- 預設排序：依改善幅度由高到低
- 自包含 HTML 頁面（無外部相依）

### 實作方式

儀表板由 `geo-content-handler` Lambda 在收到 `?action=scores` 查詢參數時提供。`action` 參數已加入所有 CloudFront cache policy 的白名單。

## 未來改進方向

- 支援批次評分和比較
- 增加更多評分維度（如可讀性、結構化程度等）
- 整合 CloudWatch 指標追蹤
