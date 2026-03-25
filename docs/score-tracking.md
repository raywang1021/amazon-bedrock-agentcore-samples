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
Each evaluation includes five dimensions (0-100), weighted to reflect AI search engine ranking priorities:

| Dimension | Weight | What it measures |
|-----------|--------|-----------------|
| **authority** | 25% | E-E-A-T signals: author credentials, organization, inline citations |
| **freshness** | 20% | Temporal signals: publish/update dates, timestamps on data |
| **relevance** | 30% | Information density: topic coverage, specificity, completeness |
| **structure** | 15% | Machine-parsability: heading hierarchy, lists, schema markup, FAQ |
| **readability** | 10% | Text quality: paragraph length, visual hierarchy, noise ratio |

`overall_score = authority×0.25 + freshness×0.20 + relevance×0.30 + structure×0.15 + readability×0.10`

Scoring is strict: most raw web content scores 30-60, only well-optimized content scores above 70.

### 3. DynamoDB Storage Structure

Items stored in DynamoDB include:

```json
{
  "url_path": "/world/3149600",
  "geo_content": "<html>...</html>",
  "original_score": {
    "overall_score": 38,
    "dimensions": {
      "authority": {"score": 45},
      "freshness": {"score": 50},
      "relevance": {"score": 35},
      "structure": {"score": 20},
      "readability": {"score": 30}
    }
  },
  "geo_score": {
    "overall_score": 72,
    "dimensions": {
      "authority": {"score": 70},
      "freshness": {"score": 75},
      "relevance": {"score": 80},
      "structure": {"score": 65},
      "readability": {"score": 70}
    }
  },
  "score_improvement": 34,
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
3. **Content truncation**: Content is truncated to 12,000 characters during scoring to control costs
4. **DynamoDB capacity**: Score data increases each item's size; ensure sufficient storage capacity
5. **Backward compatibility**: Old records with 3-dimension scores (cited_sources, statistical_addition, authoritative) remain valid; new records use 5 dimensions

## Scores Dashboard

### Offline Viewer (`scripts/ddb-viewer.html`)

A standalone HTML page for viewing and analyzing DDB records locally. No server required — open directly in a browser.

```bash
# 1. Export DDB data
aws dynamodb scan --table-name geo-content --region us-east-1 --output json > /tmp/geo-content.json

# 2. Open viewer in browser
open scripts/ddb-viewer.html        # macOS
xdg-open scripts/ddb-viewer.html    # Linux
```

Load the JSON file in the viewer. Features:
- Search and filter by host, status, URL path
- Sortable columns (click headers)
- Per-dimension score breakdown (original → GEO, with +/- delta)
- Click any row to see full metadata and GEO HTML content
- Supports both old 3-dimension and new 5-dimension score formats

### Online Dashboard

A built-in web dashboard is available at each CloudFront distribution's `?action=scores` endpoint.

A built-in web dashboard is available at each CloudFront distribution's `?action=scores` endpoint.

### Access

```
https://<cf-domain>/?ua=genaibot&action=scores
```

Examples:
- SETN: `https://dlmwhof468s34.cloudfront.net/?ua=genaibot&action=scores`
- TVBS: `https://dq324v08a4yas.cloudfront.net/?ua=genaibot&action=scores`

### Features

- Multi-tenant: each domain only sees its own DDB records (filtered by `begins_with(url_path, "{host}#")`)
- Sortable columns: Path, Status, Original Score, GEO Score, Improvement (+/-), Generation Time (ms), Created
- Default sort: by improvement descending
- Self-contained HTML page (no external dependencies)

### Implementation

The dashboard is served by `geo-content-handler` Lambda when `?action=scores` is present in the query string. The `action` parameter is whitelisted in all CloudFront cache policies.

## Future Improvements

- Batch scoring and comparison support
- CloudWatch metrics integration
