"""Lambda handler: serves GEO-optimized content from DynamoDB.

DynamoDB table schema:
  - Partition key: url_path (String) — e.g. "/blog/my-article"
  - Attributes:
    - geo_content (String) — GEO-optimized HTML/text content
    - content_type (String) — e.g. "text/html"
    - updated_at (String) — ISO 8601 timestamp
    - original_url (String) — the original page URL
"""

import json
import os
import boto3
from botocore.exceptions import ClientError

TABLE_NAME = os.environ.get("GEO_TABLE_NAME", "geo-content")
FALLBACK_STATUS = int(os.environ.get("FALLBACK_STATUS", "404"))

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)


def handler(event, context):
    """Handle API Gateway proxy request."""
    path = event.get("path", "/")
    if not path:
        path = "/"

    try:
        response = table.get_item(Key={"url_path": path})
    except ClientError as e:
        return _error_response(500, f"DynamoDB error: {e.response['Error']['Message']}")

    item = response.get("Item")
    if not item:
        return _error_response(
            FALLBACK_STATUS,
            f"No GEO content found for path: {path}",
        )

    content_type = item.get("content_type", "text/html")
    geo_content = item.get("geo_content", "")

    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": content_type,
            "X-GEO-Optimized": "true",
            "X-GEO-Updated": item.get("updated_at", "unknown"),
            "Cache-Control": "public, max-age=3600",
        },
        "body": geo_content,
    }


def _error_response(status_code: int, message: str) -> dict:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"error": message}),
    }
