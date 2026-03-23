# GEO Score Tracking

> [繁體中文版](score-tracking.zh-TW.md)

## Overview

This feature automatically evaluates and stores GEO scores before and after content rewriting to DynamoDB, enabling optimization effectiveness tracking.

## Features

### 1. Automatic Scoring
When using the `store_geo_content` tool, the system:
- Evaluates the original content's GEO score before rewriting
- Evaluates the optimized content's GEO score after rewriting
- Calculates the score improvement

### 2. Scoring Dimensions
Each evaluation includes three dimensions (0-100):
- **cited_sources**: Whether content cites sources, research, or references
- **statistical_addition**: Whether it includes specific data, percentages, statistics
- **authoritative**: Whether it has clear author attribution and authority signals (E-E-A-T)

### 3. DynamoDB Storage Structure

Items stored in DynamoDB include:

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

## Usage

### Via Agent

```python
# Agent automatically calls the store_geo_content tool
prompt = "Generate and store GEO-optimized content for https://example.com/article/123"
```

Agent returns results including score improvement:
```
GEO content stored for /article/123
Content: 8543 chars, generated in 5432ms
Score improvement: 45 → 78 (+33.0)
```

### Direct Tool Call

```python
from tools.store_geo_content import store_geo_content

result = store_geo_content("https://example.com/article/123")
print(result)
```

## Querying Score Data

### Using AWS CLI

```bash
aws dynamodb get-item \
  --table-name geo-content \
  --key '{"url_path": {"S": "/article/123"}}' \
  --region us-east-1
```

### Using Python boto3

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

## Testing

Run the test script to verify functionality:

```bash
cd test
python test_score_tracking.py
```

## Effectiveness Analysis

### Query Average Improvement

Use DynamoDB Scan to analyze average score improvement across all items:

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

### Find Top Improvements

```python
response = table.scan()
items = response["Items"]

sorted_items = sorted(
    items,
    key=lambda x: float(x.get("score_improvement", 0)),
    reverse=True
)

print("Top 10 improvements:")
for item in sorted_items[:10]:
    print(f"{item['url_path']}: +{item.get('score_improvement', 0)}")
```

## Notes

1. **Scoring cost**: Each content store triggers two LLM scoring calls (pre and post rewrite), adding processing time and cost
2. **Scoring consistency**: Uses temperature=0.1 for consistent and reproducible scores
3. **Content truncation**: Content is truncated to 8000 characters during scoring to control costs
4. **DynamoDB capacity**: Score data increases each item's size; ensure sufficient storage capacity

## Future Improvements

- Score trend analysis dashboard
- Batch scoring and comparison support
- Additional scoring dimensions (readability, structure, etc.)
- CloudWatch metrics integration
