"""Tool to generate GEO-optimized content and store it via Storage Lambda.

This bridges the GEO agent with the edge-serving infrastructure.
It rewrites a page's content for GEO, then invokes the geo-content-storage
Lambda to persist the result in DDB for CloudFront edge serving.

The Agent no longer needs DynamoDB permissions — only lambda:InvokeFunction.
"""

import json
import os
from urllib.parse import urlparse

import boto3
from strands import tool

from tools.fetch import fetch_page_text
from tools.sanitize import sanitize_web_content
from tools.prompts import GEO_REWRITE_PROMPT

GEO_STORAGE_FUNCTION_NAME = os.environ.get("GEO_STORAGE_FUNCTION_NAME", "geo-content-storage")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")




@tool
def store_geo_content(url: str) -> str:
    """Fetch a URL, rewrite its content for GEO, and store via Storage Lambda.

    Fetches the page content, rewrites it using the GEO rewriter,
    and invokes the geo-content-storage Lambda to persist the optimized
    version in DynamoDB for edge serving to AI crawlers via CloudFront.

    Args:
        url: The full URL of the page to process and store.
    """
    from model.load import load_model
    from strands import Agent
    import time as _time

    # Fetch and sanitize
    raw_text = fetch_page_text(url)
    clean_text = sanitize_web_content(raw_text)

    max_chars = 12000
    if len(clean_text) > max_chars:
        clean_text = clean_text[:max_chars] + "\n\n[Content truncated]"

    # Rewrite for GEO (output HTML for edge serving)
    rewrite_prompt = GEO_REWRITE_PROMPT + """

Output clean HTML directly without markdown code fences.
Do NOT wrap your output in ```html or ``` markers."""

    model = load_model()
    rewriter = Agent(model=model, system_prompt=rewrite_prompt, tools=[])

    gen_start = _time.time()
    result = rewriter(clean_text)
    gen_duration_ms = int((_time.time() - gen_start) * 1000)
    geo_content = str(result)

    # Strip markdown code block wrappers (Claude sometimes wraps HTML in ```html ... ```)
    import re
    geo_content = re.sub(r'^```(?:html)?\s*\n', '', geo_content)
    geo_content = re.sub(r'\n```\s*$', '', geo_content)

    # Invoke Storage Lambda instead of writing DDB directly
    parsed = urlparse(url)
    url_path = parsed.path or "/"
    if parsed.query:
        url_path = f"{url_path}?{parsed.query}"

    lambda_client = boto3.client("lambda", region_name=AWS_REGION)
    payload = {
        "url_path": url_path,
        "geo_content": geo_content,
        "original_url": url,
        "content_type": "text/html; charset=utf-8",
        "generation_duration_ms": gen_duration_ms,
        "host": parsed.netloc,
    }

    try:
        resp = lambda_client.invoke(
            FunctionName=GEO_STORAGE_FUNCTION_NAME,
            InvocationType="RequestResponse",
            Payload=json.dumps(payload),
        )
        resp_payload = json.loads(resp["Payload"].read())
        if resp.get("StatusCode") == 200 and resp_payload.get("statusCode") == 200:
            return f"GEO content stored for {url_path} ({len(geo_content)} chars, generated in {gen_duration_ms}ms)"
        else:
            error_detail = resp_payload.get("body", str(resp_payload))
            return f"Storage Lambda returned error: {error_detail}"
    except Exception as e:
        return f"Failed to invoke storage Lambda: {e}"
