"""Lambda handler: serves GEO content from DDB with 3 cache-miss modes.

Modes (via querystring ?mode=):
  - "passthrough" (default): Return original page, trigger async generation.
  - "async": Return 202 immediately, trigger async generation.
  - "sync": Wait for AgentCore to generate, return GEO content directly.

DDB status field:
  - "ready": GEO content available, serve it.
  - "processing": Generation in progress, don't re-trigger.
  - (no record): First visit, trigger generation.
"""

import json
import os
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from urllib.request import urlopen, Request

import boto3
from botocore.exceptions import ClientError

TABLE_NAME = os.environ.get("GEO_TABLE_NAME", "geo-content")
GENERATOR_FUNCTION_NAME = os.environ.get("GENERATOR_FUNCTION_NAME", "")
DEFAULT_ORIGIN_HOST = os.environ.get("DEFAULT_ORIGIN_HOST", "")
AGENT_RUNTIME_ARN = os.environ.get("AGENT_RUNTIME_ARN", "")
AGENTCORE_REGION = os.environ.get("AGENTCORE_REGION", "us-east-1")
ORIGIN_VERIFY_SECRET = os.environ.get("ORIGIN_VERIFY_SECRET", "geo-agent-cf-origin-2026")

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)
lambda_client = boto3.client("lambda")


def _get_mode(event):
    params = event.get("queryStringParameters") or {}
    mode = params.get("mode", "passthrough")
    return mode if mode in ("async", "passthrough", "sync") else "passthrough"


def _get_original_url(event, path):
    headers = event.get("headers") or {}
    host = headers.get("x-forwarded-host") or headers.get("host") or DEFAULT_ORIGIN_HOST
    return f"https://{host}{path}" if host else path


def _trigger_async(path, original_url):
    if not GENERATOR_FUNCTION_NAME:
        return
    try:
        lambda_client.invoke(
            FunctionName=GENERATOR_FUNCTION_NAME,
            InvocationType="Event",
            Payload=json.dumps({"url_path": path, "original_url": original_url}),
        )
        print(f"Async generation triggered for {path}")
    except Exception as e:
        print(f"Failed to trigger generator: {e}")


def _mark_processing(path, original_url):
    """Write a processing placeholder to DDB to prevent duplicate triggers."""
    try:
        table.put_item(
            Item={
                "url_path": path,
                "status": "processing",
                "original_url": original_url,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            ConditionExpression="attribute_not_exists(url_path)",
        )
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False  # already exists
        raise


def _fetch_original(url):
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            ct = resp.headers.get("Content-Type", "text/html; charset=utf-8")
            return body, ct
    except Exception as e:
        print(f"Fetch original failed: {e}")
        return None, None


def _invoke_agentcore_sync(url):
    if not AGENT_RUNTIME_ARN:
        return None
    client = boto3.client("bedrock-agentcore", region_name=AGENTCORE_REGION)
    payload = json.dumps({"prompt": f"請將這個頁面做 GEO 優化並存到 DynamoDB: {url}"}).encode()
    try:
        resp = client.invoke_agent_runtime(
            agentRuntimeArn=AGENT_RUNTIME_ARN,
            runtimeSessionId=str(uuid.uuid4()),
            payload=payload,
        )
        ct = resp.get("contentType", "")
        parts = []
        if "text/event-stream" in ct:
            for line in resp["response"].iter_lines(chunk_size=10):
                if line:
                    d = line.decode("utf-8")
                    if d.startswith("data: "):
                        parts.append(d[6:])
        else:
            for chunk in resp.get("response", []):
                parts.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else str(chunk))
        return "".join(parts) if parts else None
    except Exception as e:
        print(f"AgentCore sync failed: {e}")
        return None


def handler(event, context):
    handler_start = time.time()

    # Verify request comes from CloudFront
    headers = event.get("headers") or {}
    if headers.get("x-origin-verify") != ORIGIN_VERIFY_SECRET:
        return _error(403, "Forbidden")

    # Support both API GW proxy and Lambda Function URL event formats
    path = event.get("rawPath") or event.get("path") or "/"
    mode = _get_mode(event)
    original_url = _get_original_url(event, path)

    # --- Cache lookup ---
    try:
        resp = table.get_item(Key={"url_path": path})
    except ClientError as e:
        return _error(500, f"DynamoDB error: {e.response['Error']['Message']}")

    item = resp.get("Item")

    # Cache hit — ready
    if item and item.get("status") == "ready":
        handler_ms = int((time.time() - handler_start) * 1000)
        ct = item.get("content_type", "text/html")
        if "charset" not in ct.lower():
            ct += "; charset=utf-8"
        headers = {
            "Content-Type": ct,
            "X-GEO-Optimized": "true",
            "X-GEO-Source": "cache",
            "X-GEO-Created": item.get("created_at", ""),
            "X-GEO-Handler-Ms": str(handler_ms),
            "Cache-Control": "public, max-age=3600",
        }
        dur = item.get("generation_duration_ms")
        if dur is not None:
            headers["X-GEO-Duration-Ms"] = str(dur)
        return {"statusCode": 200, "headers": headers, "body": item.get("geo_content", "")}

    # Still processing
    if item and item.get("status") == "processing":
        return _passthrough_or_202(mode, original_url, path, already_triggered=True, handler_start=handler_start)

    # --- Cache miss ---
    return _passthrough_or_202(mode, original_url, path, already_triggered=False, handler_start=handler_start)


def _passthrough_or_202(mode, original_url, path, already_triggered, handler_start):
    """Handle cache miss or processing state based on mode."""

    if mode == "sync":
        # Mark processing + invoke synchronously
        if not already_triggered:
            _mark_processing(path, original_url)
        start = time.time()
        _invoke_agentcore_sync(original_url)
        agent_duration_ms = int((time.time() - start) * 1000)

        # Re-read DDB — agent should have stored content
        try:
            resp = table.get_item(Key={"url_path": path})
            item = resp.get("Item")
        except Exception:
            item = None

        handler_ms = int((time.time() - handler_start) * 1000)

        if item and item.get("status") == "ready":
            try:
                table.update_item(
                    Key={"url_path": path},
                    UpdateExpression="SET generation_duration_ms = :d, handler_duration_ms = :h, #m = :mode",
                    ExpressionAttributeNames={"#m": "mode"},
                    ExpressionAttributeValues={
                        ":d": Decimal(str(agent_duration_ms)),
                        ":h": Decimal(str(handler_ms)),
                        ":mode": "sync",
                    },
                )
            except Exception:
                pass
            return {
                "statusCode": 200,
                "headers": {
                    "Content-Type": "text/html; charset=utf-8",
                    "X-GEO-Optimized": "true",
                    "X-GEO-Source": "generated",
                    "X-GEO-Duration-Ms": str(agent_duration_ms),
                    "X-GEO-Handler-Ms": str(handler_ms),
                    "Cache-Control": "public, max-age=3600",
                },
                "body": item.get("geo_content", ""),
            }
        # Sync failed — fall through to passthrough
        return _do_passthrough(original_url, path, handler_start)

    if mode == "async":
        if not already_triggered:
            _mark_processing(path, original_url)
            _trigger_async(path, original_url)
        handler_ms = int((time.time() - handler_start) * 1000)
        return {
            "statusCode": 202,
            "headers": {
                "Content-Type": "application/json",
                "Cache-Control": "no-cache",
                "X-GEO-Handler-Ms": str(handler_ms),
            },
            "body": json.dumps({
                "status": "generating",
                "message": f"GEO content for {path} is being generated. Please retry shortly.",
            }),
        }

    # Default: passthrough
    if not already_triggered:
        _mark_processing(path, original_url)
        _trigger_async(path, original_url)
    return _do_passthrough(original_url, path, handler_start)


def _do_passthrough(original_url, path, handler_start):
    body, ct = _fetch_original(original_url)
    handler_ms = int((time.time() - handler_start) * 1000)
    if body:
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": ct or "text/html; charset=utf-8",
                "X-GEO-Source": "passthrough",
                "X-GEO-Handler-Ms": str(handler_ms),
                "Cache-Control": "no-cache",
            },
            "body": body,
        }
    return _error(502, f"Failed to fetch original content for {path}")


def _error(code, msg):
    return {
        "statusCode": code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"error": msg}),
    }
