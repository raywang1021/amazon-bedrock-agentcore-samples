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
    """Evaluate content using 5 weighted dimensions aligned with AI search engine ranking signals.

    Dimensions (weights):
      - authority (0.25): E-E-A-T signals, author/org attribution, source credibility
      - freshness (0.20): Date stamps, update markers, temporal relevance
      - relevance (0.30): Semantic completeness, topic coverage, information density
      - structure (0.15): HTML hierarchy, schema markup, machine-parsability
      - readability (0.10): Text-to-noise ratio, paragraph length, visual hierarchy
    """
    from model.load import load_model
    from strands import Agent
    import json as _json
    import re as _re

    eval_prompt = """You are an AI search engine content ranking system. You evaluate web content
the way an AI crawler (GPTBot, ClaudeBot, PerplexityBot) would assess its value for citation
in AI-generated answers.

Score this content across 5 dimensions. Be strict and precise — most web content scores 30-60,
only exceptional content scores above 80. Do NOT be generous.

## Dimensions

1. **authority** (0-100): E-E-A-T signals
   - 80+: Named author with credentials, organization identified, multiple inline citations to authoritative sources
   - 50-79: Some author/org info, a few citations but not consistent
   - 30-49: Organization mentioned but no author, minimal citations
   - <30: Anonymous, no citations, no authority signals

2. **freshness** (0-100): Temporal signals
   - 80+: Clear publish date + update date, content is current, timestamps on data points
   - 50-79: Publish date present but no update date, or dates are old
   - 30-49: Vague time references ("recently"), no explicit dates
   - <30: No temporal signals at all

3. **relevance** (0-100): Information density and completeness
   - 80+: Comprehensive topic coverage, specific data points, answers likely user questions, includes context
   - 50-79: Covers main topic but lacks depth or specificity
   - 30-49: Surface-level coverage, generic statements, filler content
   - <30: Off-topic, thin content, mostly navigation/boilerplate

4. **structure** (0-100): Machine-parsability
   - 80+: Clear heading hierarchy (H1-H3), lists/tables, schema markup (JSON-LD), FAQ sections, key-value pairs
   - 50-79: Some headings and lists, but inconsistent hierarchy
   - 30-49: Minimal structure, wall of text with occasional headings
   - <30: No structure, single block of text

5. **readability** (0-100): Human + machine readability
   - 80+: Short paragraphs (2-4 sentences), clear topic sentences, good text-to-noise ratio, visual hierarchy
   - 50-79: Reasonable paragraphs but some long blocks, decent formatting
   - 30-49: Long paragraphs, poor formatting, high noise ratio
   - <30: Unreadable, excessive ads/navigation mixed with content

## Output

Return ONLY a JSON object:
{
  "overall_score": <weighted: authority*0.25 + freshness*0.20 + relevance*0.30 + structure*0.15 + readability*0.10>,
  "dimensions": {
    "authority": {"score": <0-100>},
    "freshness": {"score": <0-100>},
    "relevance": {"score": <0-100>},
    "structure": {"score": <0-100>},
    "readability": {"score": <0-100>}
  }
}

Calculate overall_score using the exact weights above. Round to nearest integer."""

    model = load_model(temperature=0.1)
    evaluator = Agent(model=model, system_prompt=eval_prompt, tools=[])
    result = str(evaluator(f"Evaluate ({label}):\n\n{content[:12000]}"))

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

        # Update DDB with scores only (don't overwrite the full record)
        score_payload = {
            "action": "update_scores",
            "url_path": url_path,
            "host": parsed.netloc,
            "original_score": original_score,
            "geo_score": geo_score,
        }
        lambda_client.invoke(
            FunctionName=GEO_STORAGE_FUNCTION_NAME,
            InvocationType="Event",  # async — fire and forget
            Payload=json.dumps(score_payload),
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

