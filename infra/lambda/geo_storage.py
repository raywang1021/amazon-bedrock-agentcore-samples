"""Lambda: stores GEO-optimized content in DynamoDB.

Called by the Agent's store_geo_content tool via lambda:InvokeFunction.
This decouples the Agent from DynamoDB — Agent only needs lambda:InvokeFunction permission.

Expected payload:
{
    "url_path": "/world/3149600",
    "geo_content": "<html>...</html>",
    "original_url": "https://example.com/world/3149600",
    "content_type": "text/html; charset=utf-8",
    "generation_duration_ms": 12345
}
"""

import json
import os
import time
from datetime import datetime, timezone

import boto3

TABLE_NAME = os.environ.get("GEO_TABLE_NAME", "geo-content")
GEO_TTL_SECONDS = int(os.environ.get("GEO_TTL_SECONDS", "86400"))

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)


def handler(event, context):
    """Store GEO content in DynamoDB."""
    # Support both direct dict and JSON string payload
    if isinstance(event, str):
        event = json.loads(event)

    url_path = event.get("url_path")
    geo_content = event.get("geo_content")

    if not url_path or not geo_content:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "url_path and geo_content are required"}),
        }

    now = datetime.now(timezone.utc).isoformat()

    item = {
        "url_path": url_path,
        "status": "ready",
        "geo_content": geo_content,
        "content_type": event.get("content_type", "text/html; charset=utf-8"),
        "original_url": event.get("original_url", url_path),
        "created_at": now,
        "updated_at": now,
        "ttl": int(time.time()) + GEO_TTL_SECONDS,
    }

    gen_ms = event.get("generation_duration_ms")
    if gen_ms is not None:
        from decimal import Decimal
        item["generation_duration_ms"] = Decimal(str(gen_ms))

    try:
        table.put_item(Item=item)
        return {
            "statusCode": 200,
            "body": json.dumps({
                "status": "stored",
                "url_path": url_path,
                "content_length": len(geo_content),
            }),
        }
    except Exception as e:
        print(f"DDB write failed: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)}),
        }
