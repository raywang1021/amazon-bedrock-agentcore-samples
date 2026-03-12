"""Async Lambda: invokes AgentCore to generate GEO content and store in DDB.

Triggered asynchronously by geo_content_handler on cache miss.
Records created_at and generation_duration_ms for observability.
"""

import json
import os
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import boto3

TABLE_NAME = os.environ.get("GEO_TABLE_NAME", "geo-content")
AGENT_RUNTIME_ARN = os.environ.get("AGENT_RUNTIME_ARN", "")
AGENTCORE_REGION = os.environ.get("AGENTCORE_REGION", "us-east-1")

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)


def _invoke_agentcore(url: str) -> str | None:
    """Invoke AgentCore agent to generate GEO content for a URL."""
    if not AGENT_RUNTIME_ARN:
        print("AGENT_RUNTIME_ARN not set, skipping")
        return None

    client = boto3.client("bedrock-agentcore", region_name=AGENTCORE_REGION)
    prompt = f"請將這個頁面做 GEO 優化並存到 DynamoDB: {url}"
    payload = json.dumps({"prompt": prompt}).encode()
    session_id = str(uuid.uuid4())

    try:
        response = client.invoke_agent_runtime(
            agentRuntimeArn=AGENT_RUNTIME_ARN,
            runtimeSessionId=session_id,
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
        print(f"AgentCore invocation failed: {e}")
        return None


def handler(event, context):
    """Async handler: generate GEO content and store in DDB."""
    url_path = event.get("url_path", "/")
    original_url = event.get("original_url", url_path)

    print(f"Generating GEO content for {original_url} (path: {url_path})")

    start_time = time.time()
    agent_response = _invoke_agentcore(original_url)
    duration_ms = int((time.time() - start_time) * 1000)

    if not agent_response:
        print(f"AgentCore returned no content for {url_path}")
        return {"status": "failed", "url_path": url_path}

    # Agent's store_geo_content tool should have written to DDB.
    # Verify and add timing metadata.
    try:
        response = table.get_item(Key={"url_path": url_path})
        item = response.get("Item")
    except Exception as e:
        print(f"DDB read failed: {e}")
        item = None

    if item:
        # Update with generation timing
        try:
            table.update_item(
                Key={"url_path": url_path},
                UpdateExpression="SET generation_duration_ms = :d",
                ExpressionAttributeValues={":d": Decimal(str(duration_ms))},
            )
        except Exception as e:
            print(f"Failed to update timing: {e}")

        print(f"GEO content ready for {url_path} ({duration_ms}ms)")
        return {"status": "success", "url_path": url_path, "duration_ms": duration_ms}

    # Agent didn't store in DDB — store the raw response ourselves
    now = datetime.now(timezone.utc).isoformat()
    try:
        table.put_item(Item={
            "url_path": url_path,
            "geo_content": agent_response,
            "content_type": "text/html; charset=utf-8",
            "original_url": original_url,
            "created_at": now,
            "updated_at": now,
            "generation_duration_ms": Decimal(str(duration_ms)),
        })
        print(f"Stored raw agent response for {url_path} ({duration_ms}ms)")
    except Exception as e:
        print(f"Failed to store content: {e}")
        return {"status": "failed", "url_path": url_path}

    return {"status": "success", "url_path": url_path, "duration_ms": duration_ms}
