# Why AgentCore?

## What is AgentCore

AgentCore solves the core problem of bridging the infrastructure gap when moving an AI agent from prototype to production.

Calling the Bedrock Converse API directly gives you "one LLM inference." But an agent is more than a single inference — an agent needs to reason, decide which tool to use, execute the tool, reason again, decide again... This loop requires a full infrastructure stack to support it.

AgentCore provides that stack:

| Module | Problem Solved |
|--------|---------------|
| Runtime | Serverless deployment + session isolation + auto-scaling |
| Memory | Short-term session memory + cross-session long-term memory (semantic search) |
| Identity | Agent acts on behalf of users to access third-party services (OAuth, API key vault) |
| Gateway | Wraps existing APIs/Lambdas as MCP tools with unified interface + auth + rate limiting |
| Observability | Traces, spans, token usage, latency for agent execution, with built-in dashboard |
| Code Interpreter | Isolated environment for running agent-generated code |
| Browser | Managed browser for agent web interactions |

In short: Converse API is "one LLM call," AgentCore is "running an entire agent as a managed service."

## Tool Selection vs MCP

Tool selection is an LLM capability — you provide a set of tool descriptions, and the LLM decides which to call based on the prompt. This is the function calling feature supported by models like Claude and Nova.

MCP (Model Context Protocol) is a standardized interface protocol — it defines how tools are discovered, invoked, and what parameter formats to use. It solves "how tools connect," not "which tool to pick."

Their relationship:

```
MCP defines the interface format
    ↓
AgentCore Gateway wraps existing APIs/Lambdas as MCP tools
    ↓
Agent framework (Strands) sends tool descriptions to LLM
    ↓
LLM performs tool selection (decides which to use)
    ↓
Framework executes the selected tool
```

This project's 4 tools are defined directly in Python using the `@tool` decorator, without MCP. But if external systems need to be integrated in the future (CMS APIs, SEO platforms), they can be wrapped as MCP tools via AgentCore Gateway.

## AgentCore's Value in This Project

The GEO Agent has 4 tools. Users interact with it in natural language, and the agent decides which tool to use, how many times, and how to chain them.

For example (fictional example, not referring to any actual business):

> "Evaluate the GEO scores for these news sites, rewrite and deploy any that score below 60"

The agent automatically breaks this down into:

```
1. Call evaluate_geo_score for each site
   → Site A: 72 ✓  Site B: 45 ✗  Site C: 38 ✗
2. Call store_geo_content for those below 60 (rewrite + store to DDB)
3. Report results
```

More combination examples:

| User Says | Tools the Agent Combines |
|-----------|-------------------------|
| "GEO-optimize this article and deploy it" | rewrite → store_geo |
| "Evaluate this site, rewrite and deploy if below 60" | evaluate → store_geo |
| "Generate llms.txt for this site" | generate_llms_txt |
| "Compare GEO scores for these two URLs" | evaluate × 2 → compare |

This ability to trigger multi-step, multi-tool combinations from a single sentence is something a plain LLM API call cannot do.

## Multi-Tenant Shared Architecture: Adding an Origin Without Changing the Agent

This project's architecture naturally supports multi-tenancy. When you want to enable GEO service for a new website, you only need to create a new CloudFront distribution pointing to that site — the agent and Lambda require zero changes.

```
                    ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
                    │  CF Dist A   │  │  CF Dist B   │  │  CF Dist C   │
                    │ news.xxx.com │  │ 24h.shop.com │  │ blog.yyy.com │
                    └──────┬───────┘  └──────┬───────┘  └──────┬───────┘
                           │                 │                 │
                           │    CFF: AI bot? │                 │
                           └────────┬────────┘─────────────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │  Lambda (shared)     │
                         │  geo-content-handler │
                         └──────────┬──────────┘
                                    │ cache miss
                                    ▼
                         ┌─────────────────────┐
                         │  AgentCore Agent     │
                         │  (shared, auto-      │
                         │   detects content    │
                         │   type + rewrites)   │
                         └─────────────────────┘
```

Division of responsibilities:

| Layer | Responsibility | Shared? |
|-------|---------------|---------|
| CloudFront + CFF | Routing: normal users → origin, AI bots → Lambda | One per origin |
| Lambda | Serving: fetch GEO content from DynamoDB and return | Shared |
| AgentCore Agent | Intelligence: fetch content → detect type (ecommerce/news/FAQ/blog) → apply matching rewrite strategy | Shared |
| DynamoDB | Storage | Shared |

The key is the content type detection in `prompts.py`. The agent automatically classifies fetched content (ECOMMERCE, NEWS, FAQ, BLOG_TUTORIAL, GENERAL) and applies the corresponding rewrite strategy. This means:

- Adding a new origin only requires one `aws cloudformation create-stack`
- No need to write different processing logic for different types of websites
- Iterating on content strategy (tuning prompts, adding new types) only requires `agentcore deploy`, without affecting serving infra

This is the core benefit AgentCore brings to this project: extracting the complex "detect + rewrite" logic out of the infra layer and delegating it to the agent. Infra handles routing and serving, the agent handles thinking and producing — each layer does its own job, scaling independently without interference.

### What If You Don't Use This Architecture?

Without AgentCore, content type detection and rewrite logic would have to live in the Lambda itself. Common approaches:

1. **Rule-based detection in Lambda** — Use URL patterns, HTML meta tags, or DOM structure to guess content type, then map to different prompt templates. This logic grows increasingly complex; every new website type may require rule adjustments.

2. **Hardcode prompt per origin** — e.g., PChome always uses the ecommerce prompt, Taiwan Mobile always uses the FAQ prompt. Simple but inflexible — if the same site has different page types (e.g., an FAQ page on an ecommerce site), the rewrite will be wrong.

3. **Two-pass LLM calls in Lambda** — Call LLM once for classification, then again for rewriting. You're essentially hand-building the agent's tool selection loop inside Lambda, but without session management, memory, or observability, and Lambda timeout becomes a constraint.

With the current architecture, all of this is handled by the agent in a single prompt. LLMs are inherently better at understanding content semantics than regex or rule-based approaches. Adding a new content type only requires adding a strategy section in `prompts.py` — no infra changes needed.

## Real-World Deployment: Three-Layer Trigger Architecture

In production, GEO content generation has three coexisting paths:

```
                    ┌─────────────────────────────────┐
                    │       GEO Content Generation     │
                    └──────┬──────────┬───────────┬────┘
                           │          │           │
                    ┌──────▼───┐ ┌────▼─────┐ ┌───▼──────────┐
                    │ CMS      │ │ Admin    │ │ Bot's first  │
                    │ publish  │ │ natural  │ │ visit        │
                    │ webhook  │ │ language │ │ (fallback)   │
                    └──────┬───┘ └────┬─────┘ └───┬──────────┘
                           │          │           │
                    Direct call  AgentCore   Handler async
                    Bedrock API   Agent      generation
                           │          │           │
                           └──────────┴───────────┘
                                      │
                                      ▼
                               DDB (status=ready)
                                      │
                                      ▼
                           Bot visits → cache hit
```

| Trigger | Path | Best For |
|---------|------|----------|
| CMS publish webhook | Lambda calls Bedrock API directly | Automation, fixed flow, low latency |
| Admin natural language | AgentCore agent | Ad-hoc requests, batch evaluation, exploratory operations |
| Bot's first visit | Handler async generation | Fallback for pages not pre-processed |

### CMS Webhook Path

```
Editor clicks "Publish"
    │
    ├─ Normal CMS publish flow
    │
    └─ webhook → Lambda → fetch → Bedrock rewrite → DDB (ready)
                                    (background 12-20s, no one waiting)
```

This path doesn't need the agent for tool selection — the action is fixed (fetch → rewrite → store), so calling the Bedrock Converse API directly is faster and cheaper.

The first few minutes after an article is published are typically when bots are most likely to crawl (RSS feed updates, sitemap changes). If GEO content is already ready by then, the hit rate is highest.

### Summary

- AgentCore's value is in interactive scenarios: natural language → multi-tool combinations → conditional logic → automatic execution
- Fixed flows (CMS webhooks) are more efficient with direct Bedrock API calls
- Three layers coexisting ensures bots always have content available regardless of when they visit
