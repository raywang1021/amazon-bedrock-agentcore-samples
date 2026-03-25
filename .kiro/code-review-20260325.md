# Code Review — GEO Agent (2026-03-25)

## Summary

Overall the codebase is well-structured with clear separation of concerns. The multi-tenant architecture, three-layer HTML validation, and sanitize + guardrail defense-in-depth are solid design choices. Below are findings grouped by severity.

---

## Critical

### 1. `OriginVerifySecret` hardcoded as default in multiple places
- `infra/template.yaml`: `Default: "geo-agent-cf-origin-2026"`
- `infra/cloudfront-distribution.yaml`: `Default: "geo-agent-cf-origin-2026"`
- `geo_content_handler.py`: `ORIGIN_VERIFY_SECRET = os.environ.get("ORIGIN_VERIFY_SECRET", "geo-agent-cf-origin-2026")`
- Anyone reading the repo knows the default secret. If a user deploys without changing it, the Lambda is callable by anyone who sets the header.
- **Fix**: Remove the default from handler code (require it via env var), or generate a random secret in `setup.sh`.

### 2. `store_geo_content` DDB key uses `parsed.netloc` (origin host), but edge serving uses `{cf-domain}#{path}`
- When agent runs via `agentcore invoke`, it stores with key like `www.setn.com#/path`
- When edge serving triggers via CF, generator looks for `d123.cloudfront.net#/path`
- The generator has fallback logic to check both keys, but this creates duplicate DDB records for the same content.
- **Impact**: Wasted storage, potential stale data inconsistency.
- **Fix**: Consider normalizing keys to always use origin host, or cleaning up the agent-written key after copying.

### 3. AgentCore execution role missing `lambda:InvokeFunction` permission
- `setup.sh` auto-creates the role but doesn't add Lambda invoke permission.
- `store_geo_content` tool needs to call `geo-content-storage` Lambda.
- This causes silent fallback to the generator's HTML extraction path (with `\\n` artifacts).
- **Fix**: Add `lambda:InvokeFunction` policy to the role in `setup.sh` after `agentcore deploy`, or document it as a required manual step.

---

## High

### 4. `_invoke_agentcore_sync` in handler doesn't unescape SSE artifacts
- `geo_content_handler.py` `_invoke_agentcore_sync()` has the same SSE streaming parsing as `geo_generator.py` but without the JSON decode fix or unescape logic.
- If sync mode falls through to raw response parsing, it will have the same `\\n` / `""` corruption.
- **Fix**: Apply the same SSE chunk decoding and unescape logic from `geo_generator.py`.

### 5. `evaluate_geo_score` docstring still says "three dimensions"
- The docstring says "Returns scores for each perspective across three dimensions: cited_sources, statistical_addition, and authoritative" but the actual prompt now uses 5 dimensions.
- **Fix**: Update the docstring.

### 6. `samconfig.toml` committed with account-specific values
- Contains `CloudFrontDistributionArn` with account `023268648855` and distribution ID `E36FNTEQL5839Z`.
- `samconfig.toml.example` exists but the real file is also tracked.
- **Fix**: Add `samconfig.toml` to `.gitignore` (keep only `.example`), or ensure `setup.sh` always regenerates it.

---

## Medium

### 7. `template.yaml` cache policy still uses whitelist querystrings
- `template.yaml`'s `GeoCachePolicy` (for `CreateDistribution=true`) uses `QueryStringBehavior: whitelist` with `[action, mode, purge, ua]`.
- `cloudfront-distribution.yaml` was updated to `QueryStringBehavior: all`.
- These are inconsistent — the template.yaml version may break origin sites that need other querystrings.
- **Fix**: Align `template.yaml`'s cache policy with `cloudfront-distribution.yaml` (use `all`).

### 8. `rewrite_content.py` output includes `=== REWRITTEN CONTENT END ===` marker
- This marker leaks into the fallback path in `geo_generator.py` (visible in DDB data).
- The generator has a regex to strip it, but it's fragile.
- **Fix**: Remove the markers from `rewrite_content.py` output, or ensure all consumers strip them.

### 9. No retry logic for Bedrock API calls
- `_evaluate_content_score`, `_evaluate`, and rewriter agents all make single Bedrock calls with no retry.
- Bedrock can return throttling errors (429) or transient failures.
- **Fix**: Add retry with exponential backoff, or at minimum catch and log throttling errors.

### 10. `geo_content_handler.py` `_scores_dashboard` does a full table scan
- For large tables, this will be slow and expensive.
- **Fix**: Add a GSI on `host` field, or use `FilterExpression` with `begins_with` (already done, but scan is still O(n) on the full table).

### 11. `setup.sh` `sed` command for injecting ARN into samconfig.toml is fragile
- `sed -i.bak "s|parameter_overrides = \"|parameter_overrides = \"AgentRuntimeArn=...` assumes specific formatting.
- If samconfig.toml format changes or has extra whitespace, the sed will silently fail.
- **Fix**: Use Python or a more robust approach to update the TOML file.

---

## Low

### 12. `sanitize.py` patterns don't cover newer injection techniques
- Missing patterns: `<|endoftext|>`, `<tool_call>`, `<function_call>`, XML-based injection (`<request>`, `<instructions>`).
- **Fix**: Add more patterns, consider a deny-list update mechanism.

### 13. `fetch.py` fallback HTML parser is basic
- The `_TextExtractor` class doesn't handle self-closing tags or entities.
- **Fix**: Low priority since trafilatura is the primary extractor.

### 14. `generate_llms_txt.py` sitemap fetch has no sanitize
- Sitemap URLs are passed to the LLM without sanitization.
- **Fix**: Apply `sanitize_web_content` to sitemap content too.

### 15. Lambda functions hardcode `python3.12` but agent uses `PYTHON_3_10`
- `template.yaml` Lambda runtime is `python3.12`, AgentCore runtime is `PYTHON_3_10`.
- Not a bug, but worth noting for consistency.

### 16. `geo_content_handler.py` uses `urllib.request` instead of `requests`
- Lambda doesn't bundle `requests` library, so it uses stdlib `urllib.request`.
- This is intentional (no extra dependencies), but error handling is less robust.

### 17. `.bedrock_agentcore.yaml` contains absolute paths
- `entrypoint` and `source_path` use absolute paths (`/Users/yushengh/...`).
- This file is in `.gitignore` so it's not shared, but `setup.sh` generates it with `$(pwd)` which is correct.

---

## Positive Observations

- Three-layer HTML validation is a strong defense against storing non-HTML content
- Sanitize + Guardrail defense-in-depth is well-designed
- Multi-tenant architecture with `{host}#{path}` composite key is clean
- Score tracking with parallel evaluation (ThreadPoolExecutor) is efficient
- `setup.sh` one-command deploy is a good UX improvement
- CFF bot detection pattern list is comprehensive
- DDB TTL for automatic content expiration is well-implemented
