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




def _evaluate_content_score(content: str, label: str) -> dict:
    """Evaluate content and return score dict with overall_score and dimensions."""
    from model.load import MODEL_ID, AWS_REGION
    from strands.models import BedrockModel
    from strands import Agent
    import json as _json
    import re as _re

    eval_prompt = """You are a GEO scoring expert. Evaluate this content across three dimensions:

1. cited_sources (0-100): Are claims backed by sources, studies, or references?
2. statistical_addition (0-100): Does it include specific numbers, data points?
3. authoritative (0-100): Is there clear author attribution and E-E-A-T signals?

Return ONLY a JSON object with this structure:
{
  "overall_score": <0-100>,
  "dimensions": {
    "cited_sources": {"score": <0-100>},
    "statistical_addition": {"score": <0-100>},
    "authoritative": {"score": <0-100>}
  }
}"""

    model = BedrockModel(model_id=MODEL_ID, region_name=AWS_REGION, temperature=0.1)
    evaluator = Agent(model=model, system_prompt=eval_prompt, tools=[])
    result = str(evaluator(f"Evaluate ({label}):\n\n{content[:8000]}"))

    try:
        json_match = _re.search(r'\{.*\}', result, _re.DOTALL)
        if json_match:
            return _json.loads(json_match.group())
    except (_json.JSONDecodeError, AttributeError):
        pass
    return {"overall_score": 0, "dimensions": {}}



@tool
def store_geo_content(url: str) -> str:
    """Fetch a URL, rewrite its content for GEO, and store via Storage Lambda.

    Fetches the page content, rewrites it using the GEO rewriter,
    and invokes the geo-content-storage Lambda to persist the optimized
    version in DynamoDB for edge serving to AI crawlers via CloudFront.

    Evaluates GEO scores (original vs rewritten) in parallel using threads,
    then updates DDB with scores asynchronously — so content is available
    immediately without waiting for scoring to complete.

    Args:
        url: The full URL of the page to process and store.
    """
    from model.load import load_model
    from strands import Agent
    import time as _time
    from concurrent.futures import ThreadPoolExecutor

    # Fetch and sanitize
    raw_text = fetch_page_text(url)
    clean_text = sanitize_web_content(raw_text)

    max_chars = 12000
    if len(clean_text) > max_chars:
        clean_text = clean_text[:max_chars] + "\n\n[Content truncated]"

    # Rewrite for GEO (output HTML for edge serving) — this is the critical path
    rewrite_prompt = GEO_REWRITE_PROMPT + """

Output clean HTML directly without markdown code fences.
Do NOT wrap your output in ```html or ``` markers."""

    model = load_model()
    rewriter = Agent(model=model, system_prompt=rewrite_prompt, tools=[])

    gen_start = _time.time()
    result = rewriter(clean_text)
    gen_duration_ms = int((_time.time() - gen_start) * 1000)
    geo_content = str(result)

    # Strip markdown code block wrappers
    import re
    geo_content = re.sub(r'^```(?:html)?\s*\n', '', geo_content)
    geo_content = re.sub(r'\n```\s*$', '', geo_content)

    # Strip any conversational prefix before the first HTML tag.
    # The rewriter sometimes outputs "Here's the optimized content:" before HTML.
    html_start = re.search(r'<(?:!doctype|html|head|body|article|section|div|h[1-6]|main|header|nav|p\b)', geo_content, re.IGNORECASE)
    if html_start and html_start.start() > 0:
        geo_content = geo_content[html_start.start():]

    # Final guard: if geo_content doesn't look like HTML at all, bail out
    if not geo_content.strip().startswith('<'):
        return f"Rewriter did not produce HTML for {url}, skipping storage"

    # Store content immediately (don't wait for scoring)
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
        stored_ok = resp.get("StatusCode") == 200 and resp_payload.get("statusCode") == 200
    except Exception as e:
        return f"Failed to invoke storage Lambda: {e}"

    if not stored_ok:
        error_detail = resp_payload.get("body", str(resp_payload))
        return f"Storage Lambda returned error: {error_detail}"

    # Run both score evaluations in parallel (non-blocking for content serving)
    score_msg = ""
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            fut_original = pool.submit(_evaluate_content_score, clean_text, "original")
            fut_geo = pool.submit(_evaluate_content_score, geo_content, "geo-optimized")
            original_score = fut_original.result(timeout=60)
            geo_score = fut_geo.result(timeout=60)

        # Update DDB with scores via Storage Lambda (overwrite same key)
        payload["original_score"] = original_score
        payload["geo_score"] = geo_score
        lambda_client.invoke(
            FunctionName=GEO_STORAGE_FUNCTION_NAME,
            InvocationType="Event",  # async — fire and forget
            Payload=json.dumps(payload),
        )

        score_improvement = geo_score.get("overall_score", 0) - original_score.get("overall_score", 0)
        score_msg = (
            f"\nScore: {original_score.get('overall_score', 0)} → "
            f"{geo_score.get('overall_score', 0)} (+{score_improvement:.1f})"
        )
    except Exception as e:
        score_msg = f"\nScoring skipped: {e}"

    return (
        f"GEO content stored for {url_path}\n"
        f"Content: {len(geo_content)} chars, generated in {gen_duration_ms}ms"
        f"{score_msg}"
    )

