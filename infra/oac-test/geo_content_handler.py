"""Lambda handler: serves GEO content from DDB with 3 cache-miss modes.

Modes (via querystring ?mode=):
  - "passthrough" (default): Return original page, trigger async generation.
  - "async": Return 202 immediately, trigger async generation.
  - "sync": Wait for AgentCore to generate, return GEO content directly.

Purge (via querystring ?purge=true):
  - Deletes the DDB record for the requested path.
  - Next bot visit will trigger fresh generation.

DDB status field:
  - "ready": GEO content available, serve it.
  - "processing": Generation in progress, don't re-trigger.
  - (no record): First visit, trigger generation.

TTL:
  - All DDB records include a `ttl` field (Unix timestamp).
  - Default: 86400 seconds (24 hours). Configurable via GEO_TTL_SECONDS env var.
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
GEO_TTL_SECONDS = int(os.environ.get("GEO_TTL_SECONDS", "86400"))  # 24h default
PROCESSING_TIMEOUT_SECONDS = int(os.environ.get("PROCESSING_TIMEOUT_SECONDS", "300"))  # 5min default
CF_DISTRIBUTION_ID = os.environ.get("CF_DISTRIBUTION_ID", "")

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)
lambda_client = boto3.client("lambda")


def _get_mode(event):
    params = event.get("queryStringParameters") or {}
    mode = params.get("mode", "passthrough")
    return mode if mode in ("async", "passthrough", "sync") else "passthrough"


def _is_purge(event):
    params = event.get("queryStringParameters") or {}
    return params.get("purge", "").lower() in ("true", "1", "yes")


def _ttl_value():
    return int(time.time()) + GEO_TTL_SECONDS


def _get_original_url(event, path):
    # Use DEFAULT_ORIGIN_HOST (CloudFront domain) to fetch original content.
    # Don't use ALB host header — it would route back to Lambda.
    # Don't include querystring — ?ua=genaibot would re-trigger CFF.
    host = DEFAULT_ORIGIN_HOST
    if not host:
        headers = event.get("headers") or {}
        host = headers.get("x-forwarded-host") or headers.get("host") or ""
    return f"https://{host}{path}" if host else path


def _trigger_async(path, original_url, host="", mode="passthrough"):
    if not GENERATOR_FUNCTION_NAME:
        return
    try:
        payload = {"url_path": path, "original_url": original_url, "mode": mode}
        if host:
            payload["host"] = host
        lambda_client.invoke(
            FunctionName=GENERATOR_FUNCTION_NAME,
            InvocationType="Event",
            Payload=json.dumps(payload),
        )
        print(f"Async generation triggered for {path}")
    except Exception as e:
        print(f"Failed to trigger generator: {e}")


def _mark_processing(path, original_url, host="", mode="passthrough"):
    """Write a processing placeholder to DDB to prevent duplicate triggers."""
    try:
        item = {
            "url_path": path,
            "status": "processing",
            "original_url": original_url,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "ttl": _ttl_value(),
            "mode": mode,
        }
        if host:
            item["host"] = host
        table.put_item(
            Item=item,
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

    # Support both ALB and Function URL event formats
    # ALB: event["path"], Function URL: event["rawPath"]
    path = event.get("rawPath") or event.get("path") or "/"
    mode = _get_mode(event)
    original_url = _get_original_url(event, path)
    host = headers.get("x-forwarded-host") or headers.get("host") or ""

    # --- Purge ---
    if _is_purge(event):
        try:
            table.delete_item(Key={"url_path": path})
            print(f"Purged {path}")
            cf_invalidated = _invalidate_cf_cache(path)
            result = {"status": "purged", "url_path": path}
            if cf_invalidated:
                result["cf_invalidation"] = cf_invalidated
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "application/json", "Cache-Control": "no-cache"},
                "body": json.dumps(result),
            }
        except Exception as e:
            return _error(500, f"Purge failed: {e}")

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
        # Check if processing is stale (exceeded timeout)
        if _is_processing_stale(item):
            print(f"Stale processing record for {path}, resetting")
            try:
                table.delete_item(Key={"url_path": path})
            except Exception:
                pass
            return _passthrough_or_202(mode, original_url, path, already_triggered=False, handler_start=handler_start, host=host)
        return _passthrough_or_202(mode, original_url, path, already_triggered=True, handler_start=handler_start, host=host)

    # --- Cache miss ---
    return _passthrough_or_202(mode, original_url, path, already_triggered=False, handler_start=handler_start, host=host)


def _passthrough_or_202(mode, original_url, path, already_triggered, handler_start, host=""):
    """Handle cache miss or processing state based on mode."""

    if mode == "sync":
        # Pre-check: fetch original to verify it's text content
        body, ct = _fetch_original(original_url)
        if body and not _is_text_content(ct):
            handler_ms = int((time.time() - handler_start) * 1000)
            return {
                "statusCode": 200,
                "headers": {
                    "Content-Type": ct,
                    "X-GEO-Source": "passthrough-skip",
                    "X-GEO-Handler-Ms": str(handler_ms),
                    "Cache-Control": "no-cache",
                },
                "body": body,
            }
        # Mark processing + invoke synchronously
        if not already_triggered:
            _mark_processing(path, original_url, host, mode="sync")
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
            _mark_processing(path, original_url, host, mode="async")
            _trigger_async(path, original_url, host, mode="async")
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
    # Fetch original first, skip GEO generation for non-text content
    body, ct = _fetch_original(original_url)
    if body and not _is_text_content(ct):
        handler_ms = int((time.time() - handler_start) * 1000)
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": ct,
                "X-GEO-Source": "passthrough-skip",
                "X-GEO-Handler-Ms": str(handler_ms),
                "Cache-Control": "no-cache",
            },
            "body": body,
        }
    if not already_triggered:
        _mark_processing(path, original_url, host, mode="passthrough")
        _trigger_async(path, original_url, host, mode="passthrough")
    return _do_passthrough_with_body(body, ct, path, handler_start)


def _do_passthrough(original_url, path, handler_start):
    body, ct = _fetch_original(original_url)
    return _do_passthrough_with_body(body, ct, path, handler_start)


def _do_passthrough_with_body(body, ct, path, handler_start):
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


def _is_text_content(content_type):
    """Check if content-type is text-based (HTML, plain text, XML, JSON, etc.)."""
    if not content_type:
        return True  # assume text if unknown
    ct_lower = content_type.lower().split(";")[0].strip()
    return ct_lower.startswith("text/") or ct_lower in (
        "application/json",
        "application/xml",
        "application/xhtml+xml",
    )


def _is_processing_stale(item):
    """Check if a processing record has exceeded the timeout."""
    created_at = item.get("created_at", "")
    if not created_at:
        return True  # no timestamp = treat as stale
    try:
        created = datetime.fromisoformat(created_at)
        age_seconds = (datetime.now(timezone.utc) - created).total_seconds()
        return age_seconds > PROCESSING_TIMEOUT_SECONDS
    except (ValueError, TypeError):
        return True


def _invalidate_cf_cache(path):
    """Create CloudFront cache invalidation for the given path."""
    if not CF_DISTRIBUTION_ID:
        return None
    try:
        cf_client = boto3.client("cloudfront")
        caller_ref = f"purge-{path}-{int(time.time())}"
        resp = cf_client.create_invalidation(
            DistributionId=CF_DISTRIBUTION_ID,
            InvalidationBatch={
                "Paths": {"Quantity": 1, "Items": [path]},
                "CallerReference": caller_ref,
            },
        )
        inv_id = resp["Invalidation"]["Id"]
        print(f"CF invalidation created: {inv_id} for {path}")
        return inv_id
    except Exception as e:
        print(f"CF invalidation failed (non-fatal): {e}")
        return None


def _error(code, msg):
    return {
        "statusCode": code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"error": msg}),
    }
