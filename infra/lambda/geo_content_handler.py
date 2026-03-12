"""Lambda handler: serves GEO content from DDB with 3 cache-miss modes.

Modes (via querystring ?mode=):
  - "passthrough" (default): Fetch original page content, return it, trigger async generation.
  - "async": Return 202 immediately, trigger async generation.
  - "sync": Wait for AgentCore to generate, return GEO content directly.

On cache hit: always returns GEO content from DDB immediately.
"""

import json
import os
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import urlencode

import boto3
from botocore.exceptions import ClientError

TABLE_NAME = os.environ.get("GEO_TABLE_NAME", "geo-content")
GENERATOR_FUNCTION_NAME = os.environ.get("GENERATOR_FUNCTION_NAME", "")
DEFAULT_ORIGIN_HOST = os.environ.get("DEFAULT_ORIGIN_HOST", "")
AGENT_RUNTIME_ARN = os.environ.get("AGENT_RUNTIME_ARN", "")
AGENTCORE_REGION = os.environ.get("AGENTCORE_REGION", "us-east-1")

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)
lambda_client = boto3.client("lambda")


def _get_mode(event):
    """Extract mode from querystring. Default: passthrough."""
    params = event.get("queryStringParameters") or {}
    mode = params.get("mode", "passthrough")
    if mode not in ("async", "passthrough", "sync"):
        mode = "passthrough"
    return mode


def _get_original_url(event, path):
    """Reconstruct original URL from headers."""
    headers = event.get("headers") or {}
    origin_host = (
        headers.get("x-forwarded-host")
        or headers.get("host")
        or DEFAULT_ORIGIN_HOST
    )
    return f"https://{origin_host}{path}" if origin_host else path


def _trigger_async_generation(path, original_url):
    """Trigger generator Lambda asynchronously."""
    if not GENERATOR_FUNCTION_NAME:
        return
    try:
        lambda_client.invoke(
            FunctionName=GENERATOR_FUNCTION_NAME,
            InvocationType="Event",
            Payload=json.dumps({
                "url_path": path,
                "original_url": original_url,
            }),
        )
        print(f"Triggered async generation for {path}")
    except Exception as e:
        print(f"Failed to trigger generator: {e}")


def _fetch_original_page(url):
    """Fetch original page content to pass through to the bot."""
    try:
        from urllib.request import urlopen, Request
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            content_type = resp.headers.get("Content-Type", "text/html")
            return body, content_type
    except Exception as e:
        print(f"Failed to fetch original page: {e}")
        return None, None


def _invoke_agentcore_sync(url):
    """Invoke AgentCore synchronously and return generated content."""
    if not AGENT_RUNTIME_ARN:
        return None

    client = boto3.client("bedrock-agentcore", region_name=AGENTCORE_REGION)
    payload = json.dumps({"prompt": f"請將這個頁面做 GEO 優化並存到 DynamoDB: {url}"}).encode()

    try:
        response = client.invoke_agent_runtime(
            agentRuntimeArn=AGENT_RUNTIME_ARN,
            runtimeSessionId=str(uuid.uuid4()),
            payload=payload,
        )
        content_type = response.get("contentType", "")
        parts = []
        if "text/event-stream" in content_type:
            for line in response["response"].iter_lines(chunk_size=10):
                if line:
                    decoded = line.decode("utf-8")
                    if decoded.startswith("data: "):
                        parts.append(decoded[6:])
        else:
            for chunk in response.get("response", []):
                if isinstance(chunk, bytes):
                    parts.append(chunk.decode("utf-8"))
                else:
                    parts.append(str(chunk))
        return "".join(parts) if parts else None
    except Exception as e:
        print(f"AgentCore sync invocation failed: {e}")
        return None
