# Code Review — GEO Agent (2026-03-25)

## Summary

Overall the codebase is well-structured with clear separation of concerns. The multi-tenant architecture, three-layer HTML validation, and sanitize + guardrail defense-in-depth are solid design choices. Below are findings grouped by severity.

---

## Critical

### 1. `OriginVerifySecret` hardcoded as default in multiple places — KEPT (documented)
- Default is suitable for demo/POC. Production guidance added to architecture docs.
- All CF distributions sharing the same Lambda must use the same secret value.

### 2. `store_geo_content` DDB key uses `parsed.netloc` — DEFERRED
- Generator fallback logic handles the key mismatch. Low risk, high change cost.

### 3. AgentCore execution role missing `lambda:InvokeFunction` permission — FIXED
- `setup.sh` now auto-adds `geo-lambda-invoke` inline policy after `agentcore deploy`.

---

## High

### 4. `_invoke_agentcore_sync` in handler doesn't unescape SSE artifacts — FIXED

### 5. `evaluate_geo_score` docstring still says "three dimensions" — FIXED

### 6. `samconfig.toml` committed with account-specific values — FIXED
- Removed from git tracking (`git rm --cached`). Already in `.gitignore`.

### 7. `template.yaml` cache policy still uses whitelist querystrings — FIXED
- Changed to `QueryStringBehavior: all`, removed `GeoOriginRequestPolicy` resource.

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
