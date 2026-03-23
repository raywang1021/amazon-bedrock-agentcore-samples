# GEO Score Tracking - Deployment Guide

> [繁體中文版](score-tracking-deployment.zh-TW.md)

## Pre-Deployment Checklist

### 1. Code Changes Confirmed

Modified files:
- ✅ `src/tools/store_geo_content.py` - Added score evaluation
- ✅ `infra/lambda/geo_storage.py` - Support for storing score fields
- ✅ `infra/lambda/geo_generator.py` - Copy score fields
- ✅ `infra/template.yaml` - Added schema comments

### 2. Test Verification

```bash
cd test
python test_score_tracking.py
```

Expected output:
```
✓ Item stored successfully!
  Original score: 45
  GEO score: 78
  Improvement: +33
✓ All score fields verified!
✓ Test completed successfully!
```

## Deployment Steps

```bash
# 1. Ensure virtual environment is active
source .venv/bin/activate

# 2. Deploy Agent (includes new scoring feature)
agentcore deploy

# 3. Deploy SAM infrastructure (Lambda functions)
sam build -t infra/template.yaml
sam deploy -t infra/template.yaml
```

## Post-Deployment Verification

### 1. Test Full Flow

```bash
agentcore invoke "Generate and store GEO-optimized content for https://example.com/test-article"
```

### 2. Check DynamoDB Data

```bash
aws dynamodb scan \
  --table-name geo-content \
  --limit 1 \
  --region us-east-1 \
  --projection-expression "url_path, original_score, geo_score, score_improvement"
```

Expected output:
```json
{
  "Items": [
    {
      "url_path": {"S": "/test-article"},
      "original_score": {"M": {"overall_score": {"N": "45"}}},
      "geo_score": {"M": {"overall_score": {"N": "78"}}},
      "score_improvement": {"N": "33"}
    }
  ]
}
```

### 3. Check Lambda Logs

```bash
aws logs tail /aws/lambda/geo-content-storage --follow
aws logs tail /aws/lambda/geo-content-generator --follow
```

## Backward Compatibility

This update is fully backward compatible:

- ✅ Existing DynamoDB items are unaffected
- ✅ Score fields are optional
- ✅ Old items without scores can still be read and served normally
- ✅ New items automatically include score data

## Cost Impact

The score tracking feature adds the following costs:

1. **Bedrock API calls**
   - 2 extra LLM calls per content store (one for pre-rewrite, one for post-rewrite scoring)
   - ~8000 tokens per scoring call
   - Estimated cost: ~$0.01-0.02 per store (model-dependent)

2. **DynamoDB storage**
   - ~1-2 KB per item (score JSON data)
   - Negligible impact (PAY_PER_REQUEST mode)

3. **Lambda execution time**
   - ~3-5 seconds added per store (scoring time)
   - Estimated cost increase: ~$0.0001 per invocation

## Optimization Options

If cost is a concern:

### Option 1: Conditional Scoring

Modify `store_geo_content.py` to score only under certain conditions:

```python
if should_track_score(url):
    original_score = _evaluate_content_score(clean_text, "original")
    geo_score = _evaluate_content_score(geo_content, "geo-optimized")
else:
    original_score = None
    geo_score = None
```

### Option 2: Sampled Scoring

Score only a percentage of requests:

```python
import random

if random.random() < 0.1:  # 10% sample rate
    original_score = _evaluate_content_score(clean_text, "original")
    geo_score = _evaluate_content_score(geo_content, "geo-optimized")
```

### Option 3: Batch Scoring

Use a separate batch process to periodically score stored content.

## Rollback Plan

To rollback to the version without score tracking:

```bash
git revert HEAD
agentcore deploy
sam build && sam deploy
```

Existing score data remains in DynamoDB and won't affect system operation.

## Monitoring Recommendations

Suggested CloudWatch alarms:

1. **Scoring failure rate** — Monitor scoring failures in Lambda error logs
2. **Execution time increase** — Monitor `store_geo_content` tool execution time; alert threshold: > 30s
3. **Cost anomalies** — Monitor Bedrock API call counts; set daily budget alerts

## Troubleshooting

### Issue 1: Scoring fails but content stores normally

**Symptom**: DynamoDB has content but no score fields

**Cause**: Scoring LLM call failed, but doesn't affect content storage

**Fix**: Check Lambda logs, verify Bedrock permissions and quotas

### Issue 2: Score fields empty after deployment

**Symptom**: Newly stored items have no scores

**Cause**: Agent code not updated or environment variable issue

**Fix**:
```bash
agentcore deploy --force
aws lambda get-function-configuration --function-name geo-content-storage
```

### Issue 3: Scoring takes too long

**Symptom**: Store operation times out

**Fix**:
- Increase Lambda timeout (in template.yaml)
- Reduce scoring content length (adjust MAX_CHARS)
- Consider using a faster model

## References

- [Score Tracking Feature](score-tracking.md)
- [Architecture](architecture.md)
- [FAQ](faq.md)
